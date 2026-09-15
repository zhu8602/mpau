# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["MPAU_DATA_DIR"] = tempfile.mkdtemp(prefix="mpau-test-")

from pipeline import copy_engine, rules  # noqa: E402

MOCK_CFG = {"base_url": "mock", "api_key": "", "model": "mock", "n_candidates": 3}


class CleanTagsTests(unittest.TestCase):
    def test_clean_tags_handles_hash_and_spaces(self):
        self.assertEqual(rules.clean_tags("#好物, 测评  #  家居"), ["好物", "测评", "家居"])

    def test_clean_tags_dedup(self):
        self.assertEqual(rules.clean_tags(["好物", "好物", "测评"]), ["好物", "测评"])

    def test_clean_tags_empty(self):
        self.assertEqual(rules.clean_tags(""), [])
        self.assertEqual(rules.clean_tags(None), [])


class ValidateTests(unittest.TestCase):
    def test_douyin_over_55_rejected(self):
        issues = rules.validate_title("douyin", "长" * 56)
        self.assertTrue(any(i["level"] == "error" for i in issues))

    def test_douyin_55_ok(self):
        issues = rules.validate_title("douyin", "好" * 55)
        self.assertFalse(any(i["level"] == "error" for i in issues))

    def test_xiaohongshu_over_20_rejected(self):
        issues = rules.validate_title("xiaohongshu", "好" * 21)
        self.assertTrue(any(i["level"] == "error" for i in issues))

    def test_banned_word_warning(self):
        issues = rules.validate_title("xiaohongshu", "全网第一好物")
        self.assertTrue(any(i["level"] == "warning" for i in issues))

    def test_jd_min_5(self):
        issues = rules.validate_title("jd", "短")
        self.assertTrue(any(i["level"] == "error" for i in issues))


class CopyEngineTests(unittest.TestCase):
    def test_mock_generate_returns_candidates(self):
        base = {"title": "新品实测真的好用", "desc": "真实体验", "tags": ["测评"]}
        result = copy_engine.generate_one("douyin", base, cfg=MOCK_CFG, n=2)
        self.assertNotIn("error", result)
        self.assertGreaterEqual(len(result["candidates"]), 2)
        for cand in result["candidates"]:
            self.assertTrue(cand["title"])
            self.assertFalse(any(i["level"] == "error" for i in cand["issues"]))

    def test_mock_generate_multi_platform(self):
        base = {"title": "办公室必备好物分享", "desc": "打工人真实分享"}
        result = copy_engine.generate_copy(
            ["douyin", "kuaishou", "tencent", "xiaohongshu"], base, cfg=MOCK_CFG, n=2
        )
        self.assertEqual(set(result.keys()), {"douyin", "kuaishou", "tencent", "xiaohongshu"})
        for p, r in result.items():
            self.assertNotIn("error", r, f"{p}: {r}")

    def test_generate_rejects_empty_title(self):
        result = copy_engine.generate_copy(["douyin"], {"title": ""}, cfg=MOCK_CFG)
        self.assertIn("error", result)

    def test_build_messages_includes_brief_and_avoid(self):
        msgs = copy_engine.build_messages(
            "douyin", {"brief": "层层拉丝", "title": ""}, avoid_titles=["旧标题A", "旧标题B"]
        )
        user = msgs[-1]["content"]
        self.assertIn("运营要求: 层层拉丝", user)
        self.assertIn("人工标题: (无", user)
        self.assertIn("旧标题A", user)
        self.assertIn("旧标题B", user)
        self.assertIn("严禁重复或高度相似", user)

    def test_build_messages_no_avoid_when_empty(self):
        msgs = copy_engine.build_messages("douyin", {"brief": "便宜", "title": "标题X"})
        user = msgs[-1]["content"]
        self.assertIn("人工标题: 标题X", user)
        self.assertNotIn("严禁重复", user)

    def test_mock_generates_from_brief_without_title(self):
        result = copy_engine.generate_copy(["douyin"], {"brief": "椰蓉面包, 层层拉丝", "title": ""}, cfg=MOCK_CFG, n=2)
        self.assertNotIn("error", result, result)
        cands = result["douyin"]["candidates"]
        self.assertGreaterEqual(len(cands), 1)
        self.assertIn("椰蓉面包", cands[0]["title"])

    def test_mock_avoids_used_titles(self):
        """mock 遵守去重要求: 传 avoid_titles 后不再返回相同标题(模拟真实 LLM)。"""
        base = {"title": "椰蓉面包"}
        r1 = copy_engine.generate_one("douyin", base, cfg=MOCK_CFG, n=1)
        t1 = r1["candidates"][0]["title"]
        r2 = copy_engine.generate_one("douyin", base, cfg=MOCK_CFG, n=1, avoid_titles=[t1])
        t2 = r2["candidates"][0]["title"]
        self.assertNotEqual(t1, t2)

    def test_generate_copy_requires_title_or_brief(self):
        result = copy_engine.generate_copy(["douyin"], {"title": "", "brief": ""}, cfg=MOCK_CFG)
        self.assertIn("error", result)
        self.assertIn("提示词", result["error"])

    def test_missing_api_key_error(self):
        cfg = {"base_url": "https://example.invalid/v1", "api_key": "", "model": "x"}
        base = {"title": "测试标题"}
        result = copy_engine.generate_one("douyin", base, cfg=cfg)
        self.assertIn("error", result)
        self.assertIn("API Key", result["error"])

    def test_extract_json_strips_fences(self):
        text = '```json\n{"candidates": [{"title": "a", "desc": "", "tags": []}]}\n```'
        payload = copy_engine._extract_json(text)
        self.assertEqual(payload["candidates"][0]["title"], "a")

    def test_extract_json_first_balanced_object_with_trailing_text(self):
        text = '说明文字\n{"candidates": [{"title": "a", "desc": "", "tags": []}]}\n后续解释'
        payload = copy_engine._extract_json(text)
        self.assertEqual(payload["candidates"][0]["title"], "a")

    def test_extract_json_multiple_objects_takes_first(self):
        text = '{"a": 1} {"b": 2}'
        payload = copy_engine._extract_json(text)
        self.assertEqual(payload, {"a": 1})

    def test_extract_json_trailing_comma_repaired(self):
        text = '{"candidates": [{"title": "a", "desc": "", "tags": [],},],}'
        payload = copy_engine._extract_json(text)
        self.assertEqual(payload["candidates"][0]["title"], "a")

    def test_extract_json_brace_inside_string(self):
        text = '{"title": "带}花括号", "candidates": [{"title": "a", "desc": "", "tags": []}]}'
        payload = copy_engine._extract_json(text)
        self.assertEqual(payload["title"], "带}花括号")
        self.assertEqual(payload["candidates"][0]["title"], "a")

    def test_generate_one_retries_on_bad_json(self):
        from unittest import mock

        good = '{"candidates": [{"title": "好物推荐", "desc": "实测", "tags": ["测评"]}, {"title": "好物推荐2", "desc": "", "tags": []}]}'
        with mock.patch.object(copy_engine, "_call_llm", side_effect=["不是 JSON 的回复", good]) as m:
            result = copy_engine.generate_one("kuaishou", {"title": "测试标题"}, cfg=MOCK_CFG, n=2)
            self.assertNotIn("error", result)
            self.assertEqual(m.call_count, 2)
            self.assertEqual(m.call_args_list[1][1].get("temperature"), 0.5)

    def test_generate_one_fails_with_snippet_after_retry(self):
        from unittest import mock

        with mock.patch.object(copy_engine, "_call_llm", side_effect=["坏回复一", "坏回复二"]) as m:
            result = copy_engine.generate_one("tencent", {"title": "测试标题"}, cfg=MOCK_CFG)
            self.assertIn("error", result)
            self.assertIn("片段", result["error"])
            self.assertEqual(m.call_count, 2)


class GoodsTitleTests(unittest.TestCase):
    def test_mock_goods_title_from_brief(self):
        result = copy_engine.generate_goods_title(
            {"title": "", "brief": "卖点: 椰蓉面包层层拉丝"}, cfg=MOCK_CFG
        )
        self.assertNotIn("error", result)
        self.assertTrue(result["title"])
        self.assertLessEqual(len(result["title"]), copy_engine.GOODS_TITLE_MAX)
        self.assertIn("椰蓉面包", result["title"])

    def test_mock_goods_title_avoids_used(self):
        """mock 遵守去重要求: 传 avoid 后不再返回相同短标题(模拟真实 LLM)。"""
        base = {"title": "椰蓉面包"}
        t1 = copy_engine.generate_goods_title(base, cfg=MOCK_CFG)["title"]
        t2 = copy_engine.generate_goods_title(base, cfg=MOCK_CFG, avoid=[t1])["title"]
        self.assertNotEqual(t1, t2)

    def test_goods_title_requires_title_or_brief(self):
        cfg = {"base_url": "https://example.invalid/v1", "api_key": "k", "model": "x"}
        result = copy_engine.generate_goods_title({"title": "", "brief": ""}, cfg=cfg)
        self.assertIn("error", result)
        self.assertIn("提示词", result["error"])


if __name__ == "__main__":
    unittest.main()
