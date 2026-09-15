# -*- coding: utf-8 -*-
"""测试账号昵称元数据: 写入/读取/持久化/空值跳过。

注意: 必须在导入 pipeline 之前强制设置 MPAU_DATA_DIR 隔离测试数据库。
unittest discover 按字母序在单进程内导入所有测试模块, 任何模块先导入
pipeline.store 都会把 DATA_DIR 绑到真实数据目录, 后续模块的 setdefault 全部失效。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["MPAU_DATA_DIR"] = tempfile.mkdtemp(prefix="mpau-test-")

from pipeline import account_meta


class TestAccountMeta(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "accounts.json"
        self.patcher = patch.object(account_meta, "META_PATH", self.path)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def test_set_and_get_nickname(self):
        account_meta.set_nickname("douyin", "1144", "冰绮z")
        self.assertEqual(account_meta.nickname_for("douyin", "1144"), "冰绮z")
        self.assertEqual(account_meta.nicknames_for("douyin"), {"1144": "冰绮z"})

    def test_persisted_to_disk(self):
        account_meta.set_nickname("kuaishou", "aa", "zhu")
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(raw["kuaishou"]["aa"]["nickname"], "zhu")

    def test_empty_nickname_not_written(self):
        account_meta.set_nickname("douyin", "x", "")
        account_meta.set_nickname("douyin", "y", "   ")
        self.assertEqual(account_meta.nicknames_for("douyin"), {})

    def test_update_overwrites(self):
        account_meta.set_nickname("douyin", "1144", "旧名")
        account_meta.set_nickname("douyin", "1144", "新名")
        self.assertEqual(account_meta.nickname_for("douyin", "1144"), "新名")

    def test_missing_returns_empty(self):
        self.assertEqual(account_meta.nickname_for("douyin", "nonexistent"), "")

    def test_remove_nickname(self):
        account_meta.set_nickname("douyin", "1144", "冰绮z")
        account_meta.set_nickname("douyin", "33", "另一个")
        account_meta.remove_nickname("douyin", "1144")
        self.assertEqual(account_meta.nickname_for("douyin", "1144"), "")
        self.assertEqual(account_meta.nickname_for("douyin", "33"), "另一个")
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertNotIn("1144", raw["douyin"])

    def test_remove_nickname_empties_platform(self):
        account_meta.set_nickname("douyin", "1144", "冰绮z")
        account_meta.remove_nickname("douyin", "1144")
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertNotIn("douyin", raw)

    def test_remove_nickname_missing_noop(self):
        account_meta.remove_nickname("douyin", "ghost")
        self.assertEqual(self.path.exists(), False)  # 什么都没写

    def test_cookie_stem_normalized_to_alias(self):
        """上传器侧常传 Cookie 文件 stem(douyin_1144), 写入键必须归一化为别名(1144)。"""
        account_meta.set_nickname("douyin", "douyin_1144", "冰绮z")
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertIn("1144", raw["douyin"])
        self.assertNotIn("douyin_1144", raw["douyin"])
        self.assertEqual(account_meta.nickname_for("douyin", "1144"), "冰绮z")
        # 删除也走同一归一化
        account_meta.remove_nickname("douyin", "douyin_1144")
        self.assertEqual(account_meta.nickname_for("douyin", "1144"), "")

    def test_alias_starting_with_platform_name_not_stripped(self):
        """别名本身恰好以平台名开头但无下划线前缀边界时, 不应误剥。"""
        account_meta.set_nickname("douyin", "douyin1", "某号")
        self.assertEqual(account_meta.nickname_for("douyin", "douyin1"), "某号")


if __name__ == "__main__":
    unittest.main()
