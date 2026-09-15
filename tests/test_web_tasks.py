# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["MPAU_DATA_DIR"] = tempfile.mkdtemp(prefix="mpau-web-test-")

from web import app as webapp  # noqa: E402


class WebTaskLockTests(unittest.TestCase):
    def test_run_task_does_not_deadlock_tasks_lock(self):
        """回归: run_task 线程内嵌套 _persist_task 不能把 _tasks_lock 锁死。"""
        webapp.store.init_db()
        task = webapp.create_task(
            "upload", "douyin", "locktest", "死锁回归测试",
            ["batch", "status", "--batch-id", "nonexistent"],
        )
        deadline = time.time() + 40
        while time.time() < deadline:
            with webapp._tasks_lock:
                if task["status"] in ("success", "failed", "canceled"):
                    break
            time.sleep(0.2)
        self.assertIn(task["status"], ("success", "failed", "canceled"))

    def test_tasks_lock_is_reentrant(self):
        """RLock 语义: 同一线程可嵌套加锁(嵌套路径曾在 run_task 中自死锁)。"""
        with webapp._tasks_lock:
            with webapp._tasks_lock:
                pass

    def test_suggest_account_name_avoids_collision(self):
        """账号名留空自动分配: {platform}1 起, 跳过已存在的。"""
        with mock.patch.object(webapp, "list_accounts", return_value=["1144", "test"]):
            self.assertEqual(webapp.suggest_account_name("douyin"), "douyin1")
        with mock.patch.object(webapp, "list_accounts", return_value=["douyin1", "douyin2"]):
            self.assertEqual(webapp.suggest_account_name("douyin"), "douyin3")

    def test_clear_login_qrcodes_scoped_to_account(self):
        """多账号并发登录: 清理只作用于指定平台+账号, 不影响其他账号的码。"""
        tmp = Path(tempfile.mkdtemp(prefix="mpau-qrcodes-"))
        try:
            (tmp / "douyin_s1_login_qrcode_20260820_101010.png").write_bytes(b"a")
            (tmp / "douyin_s2_login_qrcode_20260820_101011.png").write_bytes(b"b")
            (tmp / "kuaishou_s1_login_qrcode_20260820_101012.png").write_bytes(b"c")
            with mock.patch.object(webapp, "COOKIES_DIR", tmp):
                webapp.clear_login_qrcodes("douyin", "s1")
                names = sorted(p.name for p in tmp.glob("*_login_qrcode_*.png"))
                self.assertEqual(names, [
                    "douyin_s2_login_qrcode_20260820_101011.png",
                    "kuaishou_s1_login_qrcode_20260820_101012.png",
                ])
                webapp.clear_login_qrcodes()
                self.assertEqual(list(tmp.glob("*_login_qrcode_*.png")), [])
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_latest_qrcodes_parses_platform_and_account(self):
        """latest_qrcodes 从文件名解析 platform/account(前端按账号匹配二维码)。"""
        tmp = Path(tempfile.mkdtemp(prefix="mpau-qrcodes-"))
        try:
            (tmp / "douyin_shop1_login_qrcode_20260820_101010.png").write_bytes(b"a")
            (tmp / "kuaishou_ks1_login_qrcode_20260820_101011.png").write_bytes(b"b")
            with mock.patch.object(webapp, "COOKIES_DIR", tmp):
                qrs = webapp.latest_qrcodes()
            self.assertEqual(len(qrs), 2)
            by_name = {q["name"]: q for q in qrs}
            self.assertEqual(by_name["douyin_shop1_login_qrcode_20260820_101010.png"]["platform"], "douyin")
            self.assertEqual(by_name["douyin_shop1_login_qrcode_20260820_101010.png"]["account"], "shop1")
            self.assertEqual(by_name["kuaishou_ks1_login_qrcode_20260820_101011.png"]["platform"], "kuaishou")
            self.assertEqual(by_name["kuaishou_ks1_login_qrcode_20260820_101011.png"]["account"], "ks1")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class WebPlanAccountsTests(unittest.TestCase):
    """/api/batch/plan 的 accounts 参数兼容 string 与 string[](多账号)。"""

    def setUp(self):
        webapp.store.init_db()
        with webapp.store._conn() as conn:  # noqa: SLF001
            for table in ("items", "videos", "batches"):
                conn.execute(f"DELETE FROM {table}")
        self.client = webapp.app.test_client()
        self.auth = {"X-MPAU-Token": webapp.web_token()}
        self.video_id = webapp.store.upsert_video("D:\\videos\\multi.mp4", sha256="msha", size=1)
        webapp.store.set_batch_videos("bmplan", [self.video_id])
        patcher = mock.patch.object(webapp, "list_accounts", return_value=["s1", "s2"])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_plan_accepts_account_list(self):
        resp = self.client.post("/api/batch/plan", json={
            "batch_id": "bmplan", "platforms": ["douyin"],
            "accounts": {"douyin": ["s1", "s2"]},
        }, headers=self.auth)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["created"], 2)  # 1 视频 × 2 账号

    def test_plan_accepts_legacy_string(self):
        resp = self.client.post("/api/batch/plan", json={
            "batch_id": "bmplan", "platforms": ["douyin"],
            "accounts": {"douyin": "s1"},
        }, headers=self.auth)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["created"], 1)

    def test_plan_rejects_unknown_account_in_list(self):
        resp = self.client.post("/api/batch/plan", json={
            "batch_id": "bmplan", "platforms": ["douyin"],
            "accounts": {"douyin": ["s1", "ghost"]},
        }, headers=self.auth)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("ghost", resp.get_json()["error"])


class WebItemUpdateTests(unittest.TestCase):
    """POST /api/batch/items/<id>: 文案字段始终生效 + 商品ID只作用本条目。

    回归背景: 早期实现只要 payload 含任一 g_* 键就直接 return(仅写商品),
    导致同请求里的 title/desc/tags/schedule 被静默丢弃而前端仍提示"已保存";
    且商品ID被同步到同视频全部平台账号条目, 改 A 条会覆盖 B 条。
    """

    def setUp(self):
        webapp.store.init_db()
        with webapp.store._conn() as conn:  # noqa: SLF001
            for table in ("items", "videos", "batches"):
                conn.execute(f"DELETE FROM {table}")
        self.client = webapp.app.test_client()
        self.auth = {"X-MPAU-Token": webapp.web_token()}
        self.video_id = webapp.store.upsert_video("D:\\videos\\item.mp4", sha256="isha", size=1)
        webapp.store.set_batch_videos("bitem", [self.video_id])
        from pipeline import batch_runner
        batch_runner.plan_batch(
            "bitem", [self.video_id], ["douyin", "kuaishou"],
            {"douyin": "s1", "kuaishou": "s1"},
        )
        items = webapp.store.list_items("bitem")
        self.dy = next(it for it in items if it["platform"] == "douyin")
        self.ks = next(it for it in items if it["platform"] == "kuaishou")

    def test_goods_id_is_item_scoped(self):
        """商品ID只写本条目: 同视频其他平台条目与视频级默认值都不受影响。"""
        resp = self.client.post(
            f"/api/batch/items/{self.dy['id']}", json={"g_id": "123456"},
            headers=self.auth,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("123456", webapp.store.get_item(self.dy["id"])["goods_json"])
        # 兄弟条目(同视频同批次其他平台/账号)保持独立
        self.assertNotIn("123456", webapp.store.get_item(self.ks["id"])["goods_json"])
        # 商品ID不回写视频级默认值
        self.assertNotIn("123456", webapp.store.get_video(self.video_id)["goods_json"])

    def test_content_fields_saved_alongside_goods(self):
        """同请求带 g_* 时, 文案字段不再被静默丢弃。"""
        resp = self.client.post(
            f"/api/batch/items/{self.dy['id']}",
            json={
                "title": "新标题", "desc": "新描述", "tags": "好物,测评",
                "schedule": "2026-06-05 20:00", "g_id": "999",
            },
            headers=self.auth,
        )
        self.assertEqual(resp.status_code, 200)
        saved = webapp.store.get_item(self.dy["id"])
        self.assertEqual(saved["title"], "新标题")
        self.assertEqual(saved["desc"], "新描述")
        self.assertEqual(saved["tags"], "好物,测评")
        self.assertEqual(saved["schedule"], "2026-06-05 20:00")
        self.assertIn("999", saved["goods_json"])

    def test_goods_link_and_title_propagate_to_video(self):
        """商品链接/短标题是视频级默认值: 同步回视频, 但仍不扩散兄弟条目。"""
        resp = self.client.post(
            f"/api/batch/items/{self.dy['id']}",
            json={"g_link": "https://x/1", "g_title": "短标题"},
            headers=self.auth,
        )
        self.assertEqual(resp.status_code, 200)
        video_goods = webapp.store.get_video(self.video_id)["goods_json"]
        self.assertIn("https://x/1", video_goods)
        self.assertIn("短标题", video_goods)
        self.assertNotIn("https://x/1", webapp.store.get_item(self.ks["id"])["goods_json"])

    def test_goods_id_only_does_not_blank_video_goods(self):
        """只改商品ID时不能把视频级商品记录清空(早期 goods_json 兜底会写空串)。"""
        webapp.store.update_video(
            self.video_id,
            goods_json='{"link": "https://keep", "title": "保留", "id": ""}',
        )
        resp = self.client.post(
            f"/api/batch/items/{self.dy['id']}", json={"g_id": "555"}, headers=self.auth,
        )
        self.assertEqual(resp.status_code, 200)
        video_goods = webapp.store.get_video(self.video_id)["goods_json"]
        self.assertIn("https://keep", video_goods)
        self.assertIn("保留", video_goods)


    def test_goods_name_is_item_scoped(self):
        """商品名称(快手挂车)与商品ID一样只作用本条目, 不扩散到兄弟条目/视频。"""
        resp = self.client.post(
            f"/api/batch/items/{self.dy['id']}",
            json={"g_name": "左烘右焙新鲜椰蓉面包椰香浓郁营养早餐80g*9包"}, headers=self.auth,
        )
        self.assertEqual(resp.status_code, 200)
        saved = webapp.store.get_item(self.dy["id"])
        self.assertIn("左烘右焙新鲜椰蓉面包", saved["goods_json"])
        self.assertNotIn("左烘右焙新鲜椰蓉面包",
                         webapp.store.get_item(self.ks["id"])["goods_json"])
        self.assertNotIn("左烘右焙新鲜椰蓉面包",
                         webapp.store.get_video(self.video_id)["goods_json"])

    def test_goods_name_saved_alongside_content(self):
        """带 g_name 时文案字段仍生效(与 g_id 同一回归面)。"""
        resp = self.client.post(
            f"/api/batch/items/{self.dy['id']}",
            json={"title": "标题A", "tags": "x,y", "g_name": "某商品名"},
            headers=self.auth,
        )
        self.assertEqual(resp.status_code, 200)
        saved = webapp.store.get_item(self.dy["id"])
        self.assertEqual(saved["title"], "标题A")
        self.assertEqual(saved["tags"], "x,y")
        self.assertIn("某商品名", saved["goods_json"])


class TaskListOverlayTests(unittest.TestCase):
    """GET /api/tasks 的内存覆盖语义。

    回归背景: 批量任务由调度器直接写 SQLite, 内存副本只在派发时登记一次
    (status=running, log=[]), 无条件覆盖会把 DB 里的 success 显示成"运行中",
    并且把真日志盖成空数组 —— 用户无法从 UI 排错。2026-09-11 实测:
    b1307-r0 DB=success 但 UI 显示 running。
    """

    def setUp(self):
        webapp.store.init_db()
        self.client = webapp.app.test_client()
        self.auth = {"X-MPAU-Token": webapp.web_token()}
        with webapp._tasks_lock:  # noqa: SLF001
            webapp._tasks.clear()

    def tearDown(self):
        with webapp._tasks_lock:  # noqa: SLF001
            webapp._tasks.clear()

    def _put_task(self, task_id, kind, status, log, error="", exit_code=None):
        webapp.store.save_task({
            "id": task_id, "kind": kind, "platform": "kuaishou", "account": "k1",
            "label": "t", "cmd": "kuaishou check --account k1", "status": status,
            "error": error, "exit": exit_code, "created": "2026-09-11 17:05:25",
            "started": "2026-09-11 17:05:25", "finished": "", "log": log,
        })

    def _register_memory(self, task_id, status, log):
        with webapp._tasks_lock:  # noqa: SLF001
            webapp._tasks[task_id] = {
                "id": task_id, "kind": "batch-upload", "platform": "kuaishou",
                "account": "k1", "label": "t", "cmd": "x", "cmd_display": "x",
                "status": status, "error": "", "exit": None,
                "created": "2026-09-11 17:05:25", "log": log,
            }

    def _fetch(self, task_id):
        tasks = self.client.get("/api/tasks", headers=self.auth).get_json()["tasks"]
        return next(t for t in tasks if t["id"] == task_id)

    def test_db_terminal_status_not_masked_by_stale_memory(self):
        """DB 已 success, 内存副本仍是 running(批量任务典型) → 必须显示 success。"""
        self._put_task("bT1", "batch-upload", "success", "line1\nline2\nline3", exit_code=0)
        self._register_memory("bT1", "running", [])
        got = self._fetch("bT1")
        self.assertEqual(got["status"], "success")
        self.assertEqual(got["exit"], 0)

    def test_db_log_used_when_memory_log_empty(self):
        """批量任务内存 log 恒为空 → 日志必须回退到 SQLite, 否则 UI 排错无从下手。"""
        self._put_task("bT2", "batch-upload", "success", "真实日志A\n真实日志B")
        self._register_memory("bT2", "running", [])
        got = self._fetch("bT2")
        self.assertEqual(len(got["log"]), 2)
        self.assertIn("真实日志A", got["log"][0])

    def test_memory_wins_while_db_still_running(self):
        """单发/登录任务: DB 未终态时内存副本权威(可能已成功但尚未落库)。"""
        self._put_task("tT3", "login", "running", "old")
        self._register_memory("tT3", "success", ["新日志1", "新日志2"])
        got = self._fetch("tT3")
        self.assertEqual(got["status"], "success")
        self.assertEqual(len(got["log"]), 2)

    def test_memory_terminal_state_wins_over_db_running(self):
        """内存已终态(取消/失败)时即便 DB 还是 running 也以内存为准。"""
        self._put_task("tT4", "upload", "running", "")
        self._register_memory("tT4", "canceled", ["已取消"])
        got = self._fetch("tT4")
        self.assertEqual(got["status"], "canceled")


if __name__ == "__main__":
    unittest.main()
