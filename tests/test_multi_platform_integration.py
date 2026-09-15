# -*- coding: utf-8 -*-
"""跨层集成测试: 批量 API → 条目 → planner 命令构建。

覆盖三个此前无测试守门的多平台组合:
  - 商品ID条目级隔离(同视频不同平台互不覆盖)
  - 快手挂车: goods_id 端到端落到 --goods-id
  - TikTok: 出现在平台注册表且命令形状正确(无 --desc, 带 --headless)
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["MPAU_DATA_DIR"] = tempfile.mkdtemp(prefix="mpau-integration-")

from pipeline import planner, store  # noqa: E402
from web import app as webapp  # noqa: E402


class MultiPlatformItemIntegrationTests(unittest.TestCase):
    def setUp(self):
        store.init_db()
        with store._conn() as conn:  # noqa: SLF001
            for table in ("items", "videos", "batches"):
                conn.execute(f"DELETE FROM {table}")
        self.client = webapp.app.test_client()
        self.auth = {"X-MPAU-Token": webapp.web_token()}

        tmp = Path(tempfile.mkdtemp(prefix="mpau-integration-vid-"))
        self.video_file = tmp / "clip.mp4"
        self.video_file.write_bytes(b"fake-video-bytes")
        self.video_id = store.upsert_video(str(self.video_file), sha256="itg-sha", size=16)
        store.set_batch_videos("bitg", [self.video_id])

        self._accounts = mock.patch.object(
            webapp, "list_accounts", return_value=["s1", "c1"]
        )
        self._accounts.start()
        self.addCleanup(self._accounts.stop)

        resp = self.client.post("/api/batch/plan", json={
            "batch_id": "bitg",
            "platforms": ["douyin", "kuaishou", "tiktok"],
            "accounts": {"douyin": ["s1"], "kuaishou": ["s1"], "tiktok": ["c1"]},
        }, headers=self.auth)
        assert resp.status_code == 200, resp.get_json()
        items = store.list_items("bitg")
        self.by_platform = {it["platform"]: it for it in items}

    def test_tiktok_registered_and_expanded(self):
        """TikTok 出现在 /api/platforms 且能参与批量展开。"""
        plats = [p["id"] for p in self.client.get("/api/platforms", headers=self.auth).get_json()]
        self.assertIn("tiktok", plats)
        self.assertEqual(len(self.by_platform), 3)

    def test_goods_id_isolated_per_platform_item(self):
        """改抖音条目商品ID: 快手/TikTok 条目与视频级默认值都不受影响。"""
        resp = self.client.post(
            f"/api/batch/items/{self.by_platform['douyin']['id']}",
            json={"g_id": "DY-999"}, headers=self.auth,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("DY-999", store.get_item(self.by_platform["douyin"]["id"])["goods_json"])
        self.assertNotIn("DY-999", store.get_item(self.by_platform["kuaishou"]["id"])["goods_json"])
        self.assertNotIn("DY-999", store.get_item(self.by_platform["tiktok"]["id"])["goods_json"])
        self.assertNotIn("DY-999", store.get_video(self.video_id)["goods_json"])

    def test_kuaishou_goods_name_reaches_command(self):
        """快手挂车: 条目里的商品名称 → planner 命令带 --goods-name(且不带 --goods-id)。

        依据 2026-09-11 真机校准: 快手走「作者服务 → 关联商品」, 只支持按名称搜索。
        """
        ks = self.by_platform["kuaishou"]
        goods = json.loads(store.get_item(ks["id"])["goods_json"])
        goods["name"] = "左烘右焙新鲜椰蓉面包椰香浓郁营养早餐80g*9包"
        store.update_item(ks["id"], goods_json=json.dumps(goods, ensure_ascii=False))

        item = store.get_item(ks["id"])
        g = json.loads(item["goods_json"])
        cmd = planner.build_upload_cmd(
            "kuaishou", item["account"], str(self.video_file),
            title="快手标题", goods_name=g.get("name", ""), goods_id=g.get("id", ""),
            headless=True,
        )
        self.assertIn("--goods-name", cmd)
        self.assertIn("左烘右焙新鲜椰蓉面包椰香浓郁营养早餐80g*9包", cmd)
        self.assertNotIn("--goods-id", cmd)

    def test_other_platforms_goods_unchanged(self):
        """其它平台的商品形态不受快手改动影响: 抖音走商品链接, 天猫走商品ID。"""
        douyin_cmd = planner.build_upload_cmd(
            "douyin", "s1", str(self.video_file), title="抖音标题",
            product_link="https://haohuo/x", product_title="短标题",
            goods_name="不该出现", headless=True,
        )
        self.assertIn("--product-link", douyin_cmd)
        self.assertNotIn("--goods-name", douyin_cmd)

        tmall_cmd = planner.build_upload_cmd(
            "tmall", "s1", str(self.video_file), title="天猫标题",
            goods_id="123456", goods_name="不该出现", headless=True,
        )
        self.assertIn("--goods-id", tmall_cmd)
        self.assertNotIn("--goods-name", tmall_cmd)

    def test_tiktok_command_shape(self):
        """TikTok 命令: 带标题/话题/--headless, 不带 --desc。"""
        tk = self.by_platform["tiktok"]
        store.update_item(tk["id"], title="TikTok title", desc="不该出现", tags="fyp,food")
        item = store.get_item(tk["id"])
        cmd = planner.build_upload_cmd(
            "tiktok", item["account"], str(self.video_file),
            title=item["title"], desc=item["desc"],
            tags=[t for t in (item["tags"] or "").split(",") if t],
            headless=True,
        )
        self.assertNotIn("--desc", cmd)
        self.assertIn("--headless", cmd)
        self.assertIn("--title", cmd)
        self.assertIn("--tags", cmd)


if __name__ == "__main__":
    unittest.main()
