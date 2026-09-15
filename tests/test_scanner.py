# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["MPAU_DATA_DIR"] = tempfile.mkdtemp(prefix="mpau-test-")

from pipeline import scanner  # noqa: E402


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="scan-"))
        (self.tmp / "sub").mkdir()
        (self.tmp / "a.mp4").write_bytes(b"a")
        (self.tmp / "sub" / "b.mov").write_bytes(b"b")
        (self.tmp / "not-video.txt").write_text("x", encoding="utf-8")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_scan_recursive_and_filter_ext(self):
        videos = scanner.scan_dir(self.tmp)
        self.assertEqual(len(videos), 2)
        names = {Path(v["path"]).name for v in videos}
        self.assertEqual(names, {"a.mp4", "b.mov"})

    def test_scan_missing_dir_raises(self):
        with self.assertRaises(FileNotFoundError):
            scanner.scan_dir(self.tmp / "nope")

    def test_sidecar_md_parsed(self):
        (self.tmp / "a.md").write_text(
            "标题: 新品实测\n描述: 真实体验\n标签: 测评,好物\n商品链接: https://x\n",
            encoding="utf-8",
        )
        side = scanner.parse_sidecar(self.tmp / "a.mp4")
        self.assertEqual(side["title"], "新品实测")
        self.assertEqual(side["desc"], "真实体验")
        self.assertEqual(side["tags"], "测评,好物")
        self.assertEqual(side["product_link"], "https://x")

    def test_sidecar_json_parsed(self):
        (self.tmp / "a.json").write_text(
            '{"标题": "JSON标题", "商品ID": "12345"}', encoding="utf-8"
        )
        side = scanner.parse_sidecar(self.tmp / "a.mp4")
        self.assertEqual(side["title"], "JSON标题")
        self.assertEqual(side["goods_id"], "12345")

    def test_csv_roundtrip(self):
        rows = [
            {
                "path": str(self.tmp / "a.mp4"),
                "base_title": "标题A",
                "base_desc": "描述",
                "base_tags": "好物,测评",
                "schedule": "2026-08-20 20:00",
                "cover": "",
                "goods_json": '{"link": "https://x", "title": "试用装", "id": "123"}',
            },
            {
                "path": str(self.tmp / "sub" / "b.mov"),
                "base_title": "标题B",
                "base_desc": "",
                "base_tags": "",
                "schedule": "",
                "cover": "",
                "goods_json": "{}",
            },
        ]
        out = self.tmp / "out.csv"
        scanner.export_csv(rows, out)
        imported = scanner.import_csv(out)
        self.assertEqual(len(imported), 2)
        by_name = {Path(r["path"]).name: r for r in imported}
        self.assertEqual(by_name["a.mp4"]["base_title"], "标题A")
        self.assertEqual(by_name["a.mp4"]["schedule"], "2026-08-20 20:00")
        self.assertIn("https://x", by_name["a.mp4"]["goods_json"])

    def test_import_csv_skips_missing_files(self):
        csv_path = self.tmp / "list.csv"
        csv_path.write_text(
            "文件名,人工标题,描述,标签,定时发布时间,封面路径,商品链接,商品短标题,商品ID\n"
            "a.mp4,标题,描述,好物,,,https://x,试用装,123\n"
            "ghost.mp4,标题2,,,,,,,\n",
            encoding="utf-8",
        )
        rows = scanner.import_csv(csv_path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["base_title"], "标题")


if __name__ == "__main__":
    unittest.main()
