# -*- coding: utf-8 -*-
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["MPAU_DATA_DIR"] = tempfile.mkdtemp(prefix="mpau-test-")

from pipeline import planner  # noqa: E402


class BuildCmdTests(unittest.TestCase):
    def test_douyin_cmd_with_product(self):
        cmd = planner.build_upload_cmd(
            "douyin", "shop1", "D:\\videos\\a.mp4",
            title="标题", desc="描述", tags=["测评", "好物"],
            product_link="https://haohuo.example/x", product_title="试用装",
            headless=True,
        )
        self.assertEqual(cmd[0:2], ["douyin", "upload-video"])
        self.assertIn("--product-link", cmd)
        self.assertIn("--product-title", cmd)
        self.assertIn("--headless", cmd)

    def test_tencent_draft_goods(self):
        cmd = planner.build_upload_cmd(
            "tencent", "shop1", "D:\\videos\\a.mp4",
            title="正文首行标题", goods_id="10000517", draft=True,
        )
        self.assertIn("--goods-id", cmd)
        self.assertIn("10000517", cmd)
        self.assertIn("--draft", cmd)

    def test_xiaohongshu_no_goods_field(self):
        cmd = planner.build_upload_cmd(
            "xiaohongshu", "shop1", "D:\\videos\\a.mp4", title="小红书标题",
        )
        self.assertNotIn("--goods-id", cmd)
        self.assertNotIn("--product-link", cmd)

    def test_tags_cleaned_of_hash(self):
        cmd = planner.build_upload_cmd(
            "kuaishou", "shop1", "D:\\videos\\a.mp4",
            title="t", tags=["#好物", "测评"],
        )
        idx = cmd.index("--tags")
        self.assertEqual(cmd[idx + 1], "好物,测评")

    def test_bilibili_removed_tiktok_restored(self):
        """B站仍不在批量注册表; TikTok 已回归(前端"更多平台"可批量发布)。"""
        self.assertNotIn("bilibili", planner.PLATFORMS)
        self.assertNotIn("bilibili", planner.PLATFORM_OPTS)
        with self.assertRaises(KeyError):
            planner.build_upload_cmd("bilibili", "shop1", "D:\\videos\\a.mp4", title="t")
        self.assertIn("tiktok", planner.PLATFORMS)
        self.assertIn("tiktok", planner.PLATFORM_OPTS)

    def test_tiktok_cmd_omits_desc_and_dry_run(self):
        """TikTok 只有标题+话题: 不能带 --desc(TikTok CLI 无此参数), 也没有 --dry-run/--goods-id。"""
        cmd = planner.build_upload_cmd(
            "tiktok", "creator1", "D:\\videos\\a.mp4",
            title="English title", desc="这段描述应被忽略", tags=["food", "review"],
            goods_id="123", dry_run=True, draft=True, headless=True,
        )
        self.assertEqual(cmd[0:2], ["tiktok", "upload-video"])
        self.assertIn("--title", cmd)
        self.assertIn("--tags", cmd)
        self.assertNotIn("--desc", cmd)
        self.assertNotIn("--dry-run", cmd)
        self.assertNotIn("--draft", cmd)
        self.assertNotIn("--goods-id", cmd)
        # 批量调度会追加 --headless/--headed, TikTok CLI 必须能解析
        self.assertIn("--headless", cmd)

    def test_kuaishou_goods_name_cmd(self):
        """快手挂车按**商品名称**: 走 --goods-name, 不产生 --goods-id / --product-link。

        依据 2026-09-11 真机校准: 入口是「作者服务 → 关联商品」, 只支持按名称搜索。
        """
        self.assertEqual(planner.PLATFORM_OPTS["kuaishou"]["goods"], "goods_name")
        cmd = planner.build_upload_cmd(
            "kuaishou", "ks1", "D:\\videos\\a.mp4",
            title="快手标题", desc="描述",
            goods_name="左烘右焙新鲜椰蓉面包椰香浓郁营养早餐80g*9包",
            goods_id="622747638382",           # 快手不支持商品ID, 应被忽略
            product_link="https://should-not-appear",
        )
        self.assertIn("--goods-name", cmd)
        self.assertIn("左烘右焙新鲜椰蓉面包椰香浓郁营养早餐80g*9包", cmd)
        self.assertNotIn("--goods-id", cmd)
        self.assertNotIn("--product-link", cmd)

    def test_kuaishou_without_goods_name_has_no_flag(self):
        cmd = planner.build_upload_cmd(
            "kuaishou", "ks1", "D:\\videos\\a.mp4", title="快手标题",
        )
        self.assertNotIn("--goods-name", cmd)


class AccountMapTests(unittest.TestCase):
    def test_parse_account_map(self):
        self.assertEqual(
            planner.parse_account_map("douyin:shop1, tencent:shop1"),
            {"douyin": ["shop1"], "tencent": ["shop1"]},
        )

    def test_parse_account_map_multi_account(self):
        """同平台重复 key 收集为多账号列表。"""
        self.assertEqual(
            planner.parse_account_map("douyin:s1, douyin:s2, kuaishou:k1"),
            {"douyin": ["s1", "s2"], "kuaishou": ["k1"]},
        )

    def test_parse_account_map_empty(self):
        self.assertEqual(planner.parse_account_map(""), {})


class ExpandTests(unittest.TestCase):
    def test_expand_1x4(self):
        video = {
            "id": 1,
            "base_title": "新品实测",
            "goods_json": json.dumps({"link": "https://x", "id": "123"}),
            "schedule": "",
        }
        items = planner.expand_items(
            video, ["douyin", "kuaishou", "tencent", "xiaohongshu"],
            {"douyin": "s1", "kuaishou": "s1", "tencent": "s1", "xiaohongshu": "s1"},
        )
        self.assertEqual(len(items), 4)
        self.assertEqual({i["platform"] for i in items}, {"douyin", "kuaishou", "tencent", "xiaohongshu"})
        self.assertTrue(all(i["account"] == "s1" for i in items))

    def test_expand_missing_account_needs_manual(self):
        video = {"id": 1, "base_title": "t", "goods_json": "{}", "schedule": ""}
        items = planner.expand_items(video, ["douyin"], {})
        self.assertEqual(items[0]["status"], "needs_manual")
        self.assertIn("账号", items[0]["error"])

    def test_expand_with_copy_map(self):
        video = {"id": 1, "base_title": "t", "goods_json": "{}", "schedule": ""}
        copy_map = {"douyin": {"title": "定制标题", "desc": "d", "tags": ["a"]}}
        items = planner.expand_items(video, ["douyin"], {"douyin": "s1"}, copy_map)
        self.assertEqual(items[0]["title"], "定制标题")
        self.assertEqual(items[0]["tags"], "a")


if __name__ == "__main__":
    unittest.main()
