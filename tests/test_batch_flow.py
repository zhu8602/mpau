# -*- coding: utf-8 -*-
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_tmp = tempfile.mkdtemp(prefix="mpau-test-store-")
os.environ["MPAU_DATA_DIR"] = _tmp

from pipeline import batch_runner, scheduler, store  # noqa: E402


class ScheduleCheckTests(unittest.TestCase):
    def test_empty_ok(self):
        self.assertEqual(scheduler.check_schedule(""), "")

    def test_bad_format(self):
        self.assertIn("格式错误", scheduler.check_schedule("2026/08/20 20:00"))

    def test_overdue_by_more_than_2h(self):
        self.assertIn("已过", scheduler.check_schedule("2000-01-01 00:00"))


class StoreTests(unittest.TestCase):
    def setUp(self):
        # 回归护栏: 数据目录必须已隔离到临时目录, 防止误删真实数据库
        self.assertTrue(
            str(store.DATA_DIR).startswith(tempfile.gettempdir()),
            f"测试数据目录未隔离! DATA_DIR={store.DATA_DIR}",
        )
        store.init_db()
        with store._conn() as conn:  # noqa: SLF001
            for table in ("items", "videos", "published", "tasks", "settings", "batches"):
                conn.execute(f"DELETE FROM {table}")

    def test_video_upsert_and_get(self):
        video_id = store.upsert_video("D:\\videos\\a.mp4", sha256="abc", base_title="标题")
        video = store.get_video(video_id)
        self.assertEqual(video["base_title"], "标题")
        store.upsert_video("D:\\videos\\a.mp4", base_title="新标题")
        self.assertEqual(store.get_video(video_id)["base_title"], "新标题")

    def test_published_dedupe_and_count(self):
        self.assertFalse(store.is_published("abc", "douyin", "s1"))
        store.mark_published("abc", "douyin", "s1")
        self.assertTrue(store.is_published("abc", "douyin", "s1"))
        self.assertGreaterEqual(store.published_count_today("s1"), 1)
        self.assertEqual(store.published_count_today("nobody"), 0)

    def test_published_count_today_by_platform(self):
        store.mark_published("a", "douyin", "s1")
        store.mark_published("b", "kuaishou", "s1")
        self.assertEqual(store.published_count_today("s1", "douyin"), 1)
        self.assertEqual(store.published_count_today("s1", "kuaishou"), 1)
        self.assertEqual(store.published_count_today("s1"), 2)
        self.assertEqual(store.published_count_today("s1", "tencent"), 0)

    def test_published_at_returns_time(self):
        store.mark_published("abc", "douyin", "s1")
        self.assertTrue(store.published_at("abc", "douyin", "s1"))
        self.assertEqual(store.published_at("abc", "douyin", "s2"), "")
        self.assertEqual(store.published_at("", "douyin", "s1"), "")

    def test_batch_videos_roundtrip_and_delete(self):
        store.set_batch_videos("bmig", [1, 2, 3])
        self.assertEqual(store.get_batch_videos("bmig"), [1, 2, 3])
        store.set_batch_videos("bmig", [9])
        self.assertEqual(store.get_batch_videos("bmig"), [9])
        self.assertEqual(store.get_batch_videos(""), [])
        self.assertEqual(store.get_batch_videos("nope"), [])
        store.create_item(batch_id="bmig", video_id=1, platform="douyin", account="s1")
        store.delete_batch("bmig")
        self.assertEqual(store.list_items("bmig"), [])
        self.assertEqual(store.get_batch_videos("bmig"), [])

    def test_migration_adds_video_ids_column(self):
        """老库迁移: init_db 为 batches 表补齐 video_ids 列。"""
        with store._conn() as conn:
            conn.execute("DROP TABLE batches")
            conn.execute(
                "CREATE TABLE batches (batch_id TEXT PRIMARY KEY, brief TEXT NOT NULL DEFAULT '', created TEXT NOT NULL DEFAULT '')"
            )
        store.init_db()
        with store._conn() as conn:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(batches)").fetchall()}
        self.assertIn("video_ids", cols)
        store.set_batch_videos("bmig2", [5])
        self.assertEqual(store.get_batch_videos("bmig2"), [5])

    def test_task_roundtrip(self):
        task = {
            "id": "t1", "kind": "upload", "platform": "douyin", "account": "s1",
            "label": "L", "cmd": ["douyin", "upload-video"], "cmd_display": "douyin upload-video",
            "status": "running", "error": "", "exit": None,
            "created": "2026-01-01 00:00:00", "started": "", "finished": "", "log": "",
        }
        store.save_task(task)
        loaded = store.load_tasks()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["cmd"], "douyin upload-video")
        store.update_task("t1", status="success", exit=0)
        self.assertEqual(store.load_tasks()[0]["status"], "success")
        store.append_task_log("t1", "hello")
        self.assertIn("hello", store.load_tasks()[0]["log"])

    def test_settings_roundtrip(self):
        store.set_setting("llm.model", "mock")
        self.assertEqual(store.get_setting("llm.model"), "mock")
        self.assertIsNone(store.get_setting("nope"))


class BatchFlowTests(unittest.TestCase):
    """端到端: 扫描 → 计划 → mock 生成 → 批准(不真正运行发布)。"""

    def setUp(self):
        # 回归护栏: 数据目录必须已隔离到临时目录, 防止误删真实数据库
        self.assertTrue(
            str(store.DATA_DIR).startswith(tempfile.gettempdir()),
            f"测试数据目录未隔离! DATA_DIR={store.DATA_DIR}",
        )
        store.init_db()
        with store._conn() as conn:  # noqa: SLF001
            for table in ("items", "videos", "published", "tasks", "settings", "batches"):
                conn.execute(f"DELETE FROM {table}")
        self.video_dir = Path(tempfile.mkdtemp(prefix="batch-videos-"))
        (self.video_dir / "001.mp4").write_bytes(b"v1" * 100)
        (self.video_dir / "002.mp4").write_bytes(b"v2" * 100)
        (self.video_dir / "001.txt").write_text("标题: 新品实测\n", encoding="utf-8")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.video_dir, ignore_errors=True)

    def _mock_cfg(self):
        return {"base_url": "mock", "api_key": "", "model": "mock", "n_candidates": 2}

    def test_scan_plan_generate_approve_flow(self):
        result = batch_runner.scan_and_register(str(self.video_dir), "btest1")
        self.assertEqual(len(result["videos"]), 2)
        self.assertTrue(result["videos"][0]["sha256"])

        # 第二条视频没有 sidecar → 填人工标题
        v2 = [v for v in result["videos"] if v["path"].endswith("002.mp4")][0]
        batch_runner.update_video_fields(v2["id"], {"base_title": "办公室好物"})

        accounts = {"douyin": "s1", "kuaishou": "s1", "tencent": "s1", "xiaohongshu": "s1"}
        planned = batch_runner.plan_batch(
            "btest1", [v["id"] for v in result["videos"]],
            ["douyin", "kuaishou", "tencent", "xiaohongshu"], accounts,
        )
        self.assertEqual(planned["created"], 8)

        generated = batch_runner.generate_batch("btest1", cfg=self._mock_cfg())
        self.assertEqual(generated["generated"], 8)
        self.assertEqual(generated["failed"], 0)

        items = store.list_items("btest1")
        for it in items:
            self.assertTrue(it["title"], f"{it['platform']} 标题为空")
            self.assertNotEqual(it["status"], "needs_manual")

        n = batch_runner.approve_items([it["id"] for it in items])
        self.assertEqual(n, 8)
        self.assertTrue(all(it["status"] == "approved" for it in store.list_items("btest1")))

        status = batch_runner.batch_status("btest1")
        self.assertEqual(status["summary"]["approved"], 8)

    def test_missing_title_marks_needs_manual(self):
        result = batch_runner.scan_and_register(str(self.video_dir), "btest2")
        v2 = [v for v in result["videos"] if v["path"].endswith("002.mp4")][0]
        # 不填标题 → 002 的视频 base_title 为空
        accounts = {"douyin": "s1"}
        batch_runner.plan_batch("btest2", [v2["id"]], ["douyin"], accounts)
        generated = batch_runner.generate_batch("btest2", cfg=self._mock_cfg())
        self.assertEqual(generated["failed"], 1)
        item = store.list_items("btest2")[0]
        self.assertEqual(item["status"], "needs_manual")
        self.assertIn("人工标题", item["error"])

    def test_retry_item(self):
        result = batch_runner.scan_and_register(str(self.video_dir), "btest3")
        v1 = [v for v in result["videos"] if v["path"].endswith("001.mp4")][0]
        batch_runner.plan_batch("btest3", [v1["id"]], ["douyin"], {"douyin": "s1"})
        item = store.list_items("btest3")[0]
        batch_runner.set_item_content(item["id"], {"status": "approved", "title": "t"})
        store.update_item(item["id"], status="failed", error="boom")
        retried = batch_runner.retry_item(item["id"])
        self.assertEqual(retried["status"], "approved")
        self.assertEqual(retried["retry"], 1)
        self.assertEqual(retried["error"], "")

    def test_scheduler_state_does_not_crash(self):
        """回归: 调度器成员名不能覆盖 threading.Thread 内部 _stop 方法。"""
        import time as _t
        sched = scheduler.start_scheduler("bnone", interval_min=1)
        _t.sleep(0.6)
        state = scheduler.scheduler_state("bnone")
        self.assertIn("alive", state)
        self.assertIsInstance(state["alive"], bool)
        scheduler.stop_scheduler("bnone")

    def test_cli_fill_maps_title_to_base_title(self):
        """回归: batch fill --title 必须落到 videos.base_title(参数名映射)。"""
        from argparse import Namespace
        result = batch_runner.scan_and_register(str(self.video_dir), "btest4")
        v2 = [v for v in result["videos"] if v["path"].endswith("002.mp4")][0]
        rc = batch_runner.dispatch_batch(
            Namespace(action="fill", video_id=v2["id"], title="人工标题A", desc=None, tags=None, schedule=None)
        )
        self.assertEqual(rc, 0)
        video = store.get_video(v2["id"])
        self.assertEqual(video["base_title"], "人工标题A")

    def test_brief_only_batch_generates_distinct_titles(self):
        """核心场景: 只填批次 AI 提示词(无逐条标题) → mock 生成成功且每个平台内标题不同(去重)。"""
        result = batch_runner.scan_and_register(str(self.video_dir), "btest5")
        store.set_batch_brief("btest5", "椰蓉面包, 层层拉丝、便宜、个头大")
        accounts = {"douyin": "s1", "kuaishou": "s1"}
        planned = batch_runner.plan_batch(
            "btest5", [v["id"] for v in result["videos"]], ["douyin", "kuaishou"], accounts,
        )
        self.assertEqual(planned["created"], 4)
        generated = batch_runner.generate_batch("btest5", cfg=self._mock_cfg())
        self.assertEqual(generated["failed"], 0)
        self.assertEqual(generated["generated"], 4)
        items = store.list_items("btest5")
        self.assertTrue(all(it["title"] for it in items))
        self.assertTrue(all(it["status"] == "draft" for it in items))
        for platform in ("douyin", "kuaishou"):
            titles = [it["title"] for it in items if it["platform"] == platform]
            self.assertEqual(len(titles), 2)
            self.assertNotEqual(titles[0], titles[1], f"{platform} 标题重复: {titles}")

    def test_brief_without_titles_no_longer_blocks(self):
        """回归: 批次有卖点时, 无逐条标题也能生成(不再 needs_manual)。"""
        result = batch_runner.scan_and_register(str(self.video_dir), "btest6")
        v2 = [v for v in result["videos"] if v["path"].endswith("002.mp4")][0]  # 无 sidecar 标题
        batch_runner.plan_batch("btest6", [v2["id"]], ["douyin"], {"douyin": "s1"})
        generated = batch_runner.generate_batch("btest6", cfg=self._mock_cfg(), brief="便宜大碗")
        self.assertEqual(generated["failed"], 0)
        item = store.list_items("btest6")[0]
        self.assertNotEqual(item["status"], "needs_manual")
        self.assertTrue(item["title"])

    def test_batch_brief_persist_and_generate_fallback(self):
        """brief 落库(去空格) + generate 不传时自动回退读批次存储值。"""
        store.set_batch_brief("btest7", " 椰蓉面包  ")
        self.assertEqual(store.get_batch_brief("btest7"), "椰蓉面包")
        result = batch_runner.scan_and_register(str(self.video_dir), "btest7")
        v2 = [v for v in result["videos"] if v["path"].endswith("002.mp4")][0]
        batch_runner.plan_batch("btest7", [v2["id"]], ["douyin"], {"douyin": "s1"})
        generated = batch_runner.generate_batch("btest7", cfg=self._mock_cfg())  # 不传 brief → 读库
        self.assertEqual(generated["failed"], 0)
        self.assertTrue(store.list_items("btest7")[0]["title"])
        # 空 batch_id 防护: 不落库不报错
        store.set_batch_brief("", "x")
        self.assertEqual(store.get_batch_brief(""), "")

    def test_no_title_no_brief_marks_needs_manual(self):
        """title 与 brief 都空 → needs_manual, 错误信息引导补填。"""
        result = batch_runner.scan_and_register(str(self.video_dir), "btest8")
        v2 = [v for v in result["videos"] if v["path"].endswith("002.mp4")][0]
        batch_runner.plan_batch("btest8", [v2["id"]], ["douyin"], {"douyin": "s1"})
        generated = batch_runner.generate_batch("btest8", cfg=self._mock_cfg(), brief="")
        self.assertEqual(generated["failed"], 1)
        item = store.list_items("btest8")[0]
        self.assertEqual(item["status"], "needs_manual")
        self.assertIn("提示词", item["error"])

    def test_quota_info_preview(self):
        """运行前额度预览: 已批准 vs 今日已发 vs 上限。"""
        result = batch_runner.scan_and_register(str(self.video_dir), "bquota")
        batch_runner.plan_batch(
            "bquota", [v["id"] for v in result["videos"]],
            ["douyin", "kuaishou"], {"douyin": "s1", "kuaishou": "s1"},
        )
        batch_runner.approve_items([it["id"] for it in store.list_items("bquota")])
        store.mark_published("abc", "douyin", "s1")  # 抖音今天已发 1 条
        info = batch_runner.quota_info("bquota", {"douyin": 2, "kuaishou": 10})
        dy = info["platforms"]["douyin"]
        self.assertEqual(dy["approved"], 2)
        self.assertEqual(dy["published"], 1)
        self.assertEqual(dy["cap"], 2)
        self.assertEqual(dy["remaining"], 1)
        self.assertEqual(dy["will_publish"], 1)
        self.assertEqual(dy["will_skip"], 1)
        ks = info["platforms"]["kuaishou"]
        self.assertEqual(ks["will_publish"], 2)
        self.assertEqual(ks["will_skip"], 0)

    def test_approve_allows_skipped(self):
        """日上限/防重发跳过的条目允许重新批准。"""
        result = batch_runner.scan_and_register(str(self.video_dir), "bskipa")
        v1 = [v for v in result["videos"] if v["path"].endswith("001.mp4")][0]
        batch_runner.plan_batch("bskipa", [v1["id"]], ["douyin"], {"douyin": "s1"})
        item = store.list_items("bskipa")[0]
        store.update_item(item["id"], status="skipped", error="已达上限")
        n = batch_runner.approve_items([item["id"]])
        self.assertEqual(n, 1)
        self.assertEqual(store.get_item(item["id"])["status"], "approved")

    def test_scheduler_skips_item_on_daily_cap(self):
        """达平台日上限: 条目被跳过并写明原因(不再空等)。"""
        import time as _t
        result = batch_runner.scan_and_register(str(self.video_dir), "bcap")
        v1 = [v for v in result["videos"] if v["path"].endswith("001.mp4")][0]
        batch_runner.plan_batch("bcap", [v1["id"]], ["douyin"], {"douyin": "s1"})
        item = store.list_items("bcap")[0]
        batch_runner.approve_items([item["id"]])
        store.mark_published("othersha", "douyin", "s1")  # 今天已发 1 条
        sched = scheduler.start_scheduler("bcap", interval_min=0.1, daily_cap=25, daily_caps={"douyin": 1})
        try:
            for _ in range(50):
                it = store.get_item(item["id"])
                if it["status"] == "skipped":
                    break
                _t.sleep(0.1)
            it = store.get_item(item["id"])
            self.assertEqual(it["status"], "skipped")
            self.assertIn("上限", it["error"])
        finally:
            scheduler.stop_scheduler("bcap")

    def test_scheduler_cap_for_fallback(self):
        s = scheduler.BatchScheduler("bcap2", daily_cap=25, daily_caps={"douyin": 1})
        self.assertEqual(s._cap_for("douyin"), 1)
        self.assertEqual(s._cap_for("xiaohongshu"), 25)

    def test_next_eligible_skips_inflight_platform_account(self):
        """并发调度: 同「平台+账号」在飞时不再取该组合的条目, 其他平台照常可取。"""
        result = batch_runner.scan_and_register(str(self.video_dir), "binfly")
        batch_runner.plan_batch(
            "binfly", [v["id"] for v in result["videos"]],
            ["douyin", "kuaishou"], {"douyin": "s1", "kuaishou": "s1"},
        )
        batch_runner.approve_items([it["id"] for it in store.list_items("binfly")])
        s = scheduler.BatchScheduler("binfly", interval_min=0.1, max_concurrent=2)
        fake = threading.Thread(target=lambda: None)
        with s._lock:
            s._in_flight[("douyin", "s1")] = fake
        eligible = s._next_eligible()
        self.assertIsNotNone(eligible)
        self.assertEqual(eligible["platform"], "kuaishou")
        with s._lock:
            s._in_flight[("kuaishou", "s1")] = fake
        self.assertIsNone(s._next_eligible())

    def test_update_item_goods_is_item_scoped(self):
        """商品ID只作用本条目: 不同平台/账号各自持有, 互不覆盖。"""
        result = batch_runner.scan_and_register(str(self.video_dir), "bgoods")
        v1 = [v for v in result["videos"] if v["path"].endswith("001.mp4")][0]
        batch_runner.plan_batch("bgoods", [v1["id"]], ["douyin", "kuaishou"], {"douyin": "s1", "kuaishou": "s1"})
        items = store.list_items("bgoods")
        dy = next(it for it in items if it["platform"] == "douyin")
        updated = batch_runner.update_item_goods(dy["id"], {"link": "https://x", "id": "123"})
        self.assertIsNotNone(updated)
        self.assertIn("https://x", updated["goods_json"])
        self.assertIn("123", updated["goods_json"])
        # 同视频其他平台条目保持独立(不再被同步覆盖)
        ks = next(it for it in store.list_items("bgoods") if it["platform"] == "kuaishou")
        self.assertNotIn("https://x", ks["goods_json"])
        self.assertNotIn("123", ks["goods_json"])
        # 视频级默认值也不被条目编辑改写(它只是新建条目的播种值)
        video = store.get_video(v1["id"])
        self.assertNotIn("https://x", video["goods_json"])

    def test_scan_registers_batch_videos(self):
        """批次隔离: 扫描时登记本批次视频清单, 不混入其他批次的视频。"""
        result = batch_runner.scan_and_register(str(self.video_dir), "breg1")
        ids = store.get_batch_videos("breg1")
        self.assertEqual(ids, [v["id"] for v in result["videos"]])
        self.assertEqual(len(ids), 2)
        # 再扫一个新批次, 各自清单互不影响
        batch_runner.scan_and_register(str(self.video_dir), "breg2")
        self.assertEqual(store.get_batch_videos("breg1"), ids)

    def test_generate_progress_callback(self):
        """生成进度回调: 每个视频处理完回调一次, 总数正确。"""
        result = batch_runner.scan_and_register(str(self.video_dir), "bprog")
        batch_runner.plan_batch("bprog", [v["id"] for v in result["videos"]], ["douyin"], {"douyin": "s1"})
        seen = []
        generated = batch_runner.generate_batch(
            "bprog", cfg=self._mock_cfg(), brief="便宜大碗",
            on_progress=lambda done, failed, total, cur: seen.append((done, failed, total, cur)),
        )
        self.assertEqual(generated["generated"], 2)
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[-1][0], 2)
        self.assertEqual(seen[-1][2], 2)

    def test_list_batches_includes_meta_only(self):
        """只有扫描记录、还没展开条目的批次也要出现在列表里。"""
        store.set_batch_videos("bmeta1", [1])
        batches = batch_runner.list_batches()
        b = next((x for x in batches if x["batch_id"] == "bmeta1"), None)
        self.assertIsNotNone(b)
        self.assertEqual(b["total"], 0)

    def test_generate_batch_defaults_to_one_candidate(self):
        """批量生成默认每条只出 1 个候选(用户审阅更轻)。"""
        result = batch_runner.scan_and_register(str(self.video_dir), "b1cand")
        v1 = [v for v in result["videos"] if v["path"].endswith("001.mp4")][0]
        batch_runner.plan_batch("b1cand", [v1["id"]], ["douyin"], {"douyin": "s1"})
        generated = batch_runner.generate_batch("b1cand", cfg=self._mock_cfg())  # cfg 里 n_candidates=2 但批处理默认 1
        self.assertEqual(generated["generated"], 1)
        item = store.list_items("b1cand")[0]
        cands = batch_runner.platform_candidates(item)
        self.assertEqual(len(cands), 1)

    def test_generate_goods_title_fill_empty_only(self):
        """商品短标题: 只填空; 写入视频及同视频全部条目; 保留已有 link/手动短标题。"""
        result = batch_runner.scan_and_register(str(self.video_dir), "bgt1")
        v1 = [v for v in result["videos"] if v["path"].endswith("001.mp4")][0]
        v2 = [v for v in result["videos"] if v["path"].endswith("002.mp4")][0]
        batch_runner.update_video_fields(v2["id"], {"base_title": "办公室好物"})
        # v1 已有手动短标题 + 商品链接 → 不覆盖
        store.update_video(
            v1["id"],
            goods_json=json.dumps({"link": "https://x", "title": "手动短标题"}, ensure_ascii=False),
        )
        batch_runner.plan_batch(
            "bgt1", [v1["id"], v2["id"]], ["douyin", "kuaishou"], {"douyin": "s1", "kuaishou": "s1"},
        )
        generated = batch_runner.generate_batch("bgt1", cfg=self._mock_cfg(), with_goods_title=True)
        self.assertEqual(generated["generated"], 4)
        self.assertEqual(generated["goods_titles"], 1)  # 只有 v2 需要生成
        self.assertEqual(generated["goods_failed"], 0)
        # v1 视频与条目均保持手动短标题
        v1_goods = json.loads(store.get_video(v1["id"])["goods_json"])
        self.assertEqual(v1_goods["title"], "手动短标题")
        self.assertEqual(v1_goods["link"], "https://x")
        # v2 视频与全部条目写入同一短标题
        v2_goods = json.loads(store.get_video(v2["id"])["goods_json"])
        self.assertTrue(v2_goods["title"])
        self.assertLessEqual(len(v2_goods["title"]), 10)
        for it in store.list_items("bgt1"):
            g = json.loads(it["goods_json"])
            if it["video_id"] == v2["id"]:
                self.assertEqual(g["title"], v2_goods["title"])
            else:
                self.assertEqual(g["title"], "手动短标题")

    def test_generate_goods_title_diverse_across_videos(self):
        """同批多个空商品视频: 生成的短标题互不相同。"""
        result = batch_runner.scan_and_register(str(self.video_dir), "bgt2")
        v2 = [v for v in result["videos"] if v["path"].endswith("002.mp4")][0]
        batch_runner.update_video_fields(v2["id"], {"base_title": "办公室好物"})
        batch_runner.plan_batch(
            "bgt2", [v["id"] for v in result["videos"]], ["douyin"], {"douyin": "s1"},
        )
        generated = batch_runner.generate_batch("bgt2", cfg=self._mock_cfg(), with_goods_title=True)
        self.assertEqual(generated["goods_titles"], 2)
        titles = {json.loads(v["goods_json"]).get("title", "") for v in store.list_videos()}
        self.assertEqual(len(titles), 2)
        self.assertTrue(all(titles))

    def test_generate_without_goods_title_keeps_goods_empty(self):
        """不开 with_goods_title: goods_json 保持不变(短标题仍为空)。"""
        result = batch_runner.scan_and_register(str(self.video_dir), "bgt3")
        v1 = [v for v in result["videos"] if v["path"].endswith("001.mp4")][0]
        batch_runner.plan_batch("bgt3", [v1["id"]], ["douyin"], {"douyin": "s1"})
        batch_runner.generate_batch("bgt3", cfg=self._mock_cfg())
        item = store.list_items("bgt3")[0]
        self.assertEqual(json.loads(item["goods_json"]).get("title", ""), "")
        self.assertEqual(json.loads(store.get_video(v1["id"])["goods_json"]).get("title", ""), "")

    # ---- 选择单条视频(单条发布并入批量) ----

    def test_add_single_video_creates_new_batch(self):
        """无批次时登记单条视频: 自动新建批次, 带 sidecar 元数据。"""
        v1 = self.video_dir / "001.mp4"
        result = batch_runner.add_video_and_register(str(v1))
        self.assertTrue(result["batch_id"].startswith("b"))
        self.assertTrue(result["added"])
        video = result["video"]
        self.assertEqual(store.get_batch_videos(result["batch_id"]), [video["id"]])
        self.assertEqual(video["base_title"], "新品实测")  # 001.txt sidecar
        self.assertTrue(video["sha256"])

    def test_add_single_video_duplicate_skipped(self):
        """同路径重复登记: added=False, 批次清单不重复。"""
        v1 = self.video_dir / "001.mp4"
        first = batch_runner.add_video_and_register(str(v1), "bsingle1")
        second = batch_runner.add_video_and_register(str(v1), "bsingle1")
        self.assertTrue(first["added"])
        self.assertFalse(second["added"])
        self.assertEqual(store.get_batch_videos("bsingle1"), [first["video"]["id"]])

    def test_add_single_video_appends_to_existing_batch(self):
        """已有批次时登记单条视频: 追加(扫描替换语义不受影响)。"""
        scanned = batch_runner.scan_and_register(str(self.video_dir), "bsingle2")
        self.assertEqual(len(scanned["videos"]), 2)
        other_dir = Path(tempfile.mkdtemp(prefix="batch-extra-"))
        try:
            extra = other_dir / "003.mp4"
            extra.write_bytes(b"v3" * 100)
            result = batch_runner.add_video_and_register(str(extra), "bsingle2")
            self.assertTrue(result["added"])
            ids = store.get_batch_videos("bsingle2")
            self.assertEqual(len(ids), 3)
            self.assertIn(result["video"]["id"], ids)
        finally:
            import shutil
            shutil.rmtree(other_dir, ignore_errors=True)

    def test_add_single_video_errors(self):
        """文件不存在 / 非视频扩展名 → 抛出明确异常。"""
        with self.assertRaises(FileNotFoundError):
            batch_runner.add_video_and_register(str(self.video_dir / "nope.mp4"), "bsingle3")
        with self.assertRaises(RuntimeError):
            batch_runner.add_video_and_register(str(self.video_dir / "001.txt"), "bsingle3")

    def test_add_single_video_then_generate(self):
        """单条链路端到端: 登记 → 填标题 → 计划 → mock 生成, 与批量完全一致。"""
        v2 = self.video_dir / "002.mp4"
        result = batch_runner.add_video_and_register(str(v2), "bsingle4")
        batch_runner.update_video_fields(result["video"]["id"], {"base_title": "办公室好物"})
        planned = batch_runner.plan_batch(
            "bsingle4", [result["video"]["id"]],
            ["douyin", "kuaishou"], {"douyin": "s1", "kuaishou": "s1"},
        )
        self.assertEqual(planned["created"], 2)
        generated = batch_runner.generate_batch("bsingle4", cfg=self._mock_cfg())
        self.assertEqual(generated["generated"], 2)
        self.assertEqual(generated["failed"], 0)
        self.assertTrue(all(it["title"] for it in store.list_items("bsingle4")))

    # ---- 多账号多样化发布 ----

    def test_plan_multi_account_expands_and_idempotent(self):
        """多账号映射: 视频×平台×账号 展开; 重复 plan 幂等; item_exists 按账号区分。"""
        result = batch_runner.scan_and_register(str(self.video_dir), "bmacc1")
        accounts = {"douyin": ["s1", "s2"], "kuaishou": ["s1"]}
        planned = batch_runner.plan_batch(
            "bmacc1", [v["id"] for v in result["videos"]],
            ["douyin", "kuaishou"], accounts,
        )
        # 2 视频 × (抖音 2 账号 + 快手 1 账号) = 6 条
        self.assertEqual(planned["created"], 6)
        for v in result["videos"]:
            self.assertTrue(store.item_exists("bmacc1", v["id"], "douyin", "s1"))
            self.assertTrue(store.item_exists("bmacc1", v["id"], "douyin", "s2"))
            self.assertTrue(store.item_exists("bmacc1", v["id"], "kuaishou", "s1"))
            self.assertIsNone(store.item_exists("bmacc1", v["id"], "kuaishou", "s2"))
        # 重复 plan 不重复创建
        again = batch_runner.plan_batch(
            "bmacc1", [v["id"] for v in result["videos"]],
            ["douyin", "kuaishou"], accounts,
        )
        self.assertEqual(again["created"], 0)
        self.assertEqual(len(store.list_items("bmacc1")), 6)

    def test_plan_multi_account_accepts_legacy_string(self):
        """旧单账号字符串格式仍兼容: 等价于单元素列表。"""
        result = batch_runner.scan_and_register(str(self.video_dir), "bmacc2")
        planned = batch_runner.plan_batch(
            "bmacc2", [v["id"] for v in result["videos"]],
            ["douyin"], {"douyin": "s1"},
        )
        self.assertEqual(planned["created"], 2)

    def test_generate_multi_account_titles_differ_per_platform(self):
        """同平台多账号: 生成标题互不相同(多样化)。"""
        result = batch_runner.scan_and_register(str(self.video_dir), "bmacc3")
        v2 = [v for v in result["videos"] if v["path"].endswith("002.mp4")][0]
        batch_runner.update_video_fields(v2["id"], {"base_title": "办公室好物"})
        accounts = {"douyin": ["s1", "s2"]}
        batch_runner.plan_batch(
            "bmacc3", [v["id"] for v in result["videos"]], ["douyin"], accounts,
        )
        generated = batch_runner.generate_batch("bmacc3", cfg=self._mock_cfg())
        self.assertEqual(generated["generated"], 4)  # 2 视频 × 2 账号
        titles = [it["title"] for it in store.list_items("bmacc3")]
        self.assertEqual(len(titles), len(set(titles)))  # 全部互不相同


if __name__ == "__main__":
    unittest.main()
