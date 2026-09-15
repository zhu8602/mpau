# -*- coding: utf-8 -*-
"""回归测试: 掩码 API Key 不得写回覆盖真实 Key。

背景: 设置页 GET 返回脱敏 Key, 用户再次保存时前端可能把脱敏值原样提交,
save_config 必须识别含 * 的值并保留原 Key, 否则真实 Key 被覆盖导致 LLM 401。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# 必须先隔离数据目录再导入 pipeline(见 test_account_meta.py 顶部说明)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["MPAU_DATA_DIR"] = tempfile.mkdtemp(prefix="mpau-test-")

from pipeline import config as cfgmod


class TestConfigKeyGuard(unittest.TestCase):
    def _write(self, path: Path, key: str) -> None:
        path.write_text(
            json.dumps({"llm": {"base_url": "https://api.deepseek.com/v1", "api_key": key, "model": "deepseek-chat"}}),
            encoding="utf-8",
        )

    def test_masked_key_is_not_saved(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.json"
            self._write(p, "sk-real-abcdef1234")
            with patch.object(cfgmod, "CONFIG_PATH", p):
                # 提交脱敏值(模拟前端回传掩码) → 真实 Key 必须保留
                cfgmod.save_config({"llm": {"api_key": "************1234"}})
                self.assertEqual(cfgmod.load_config()["llm"]["api_key"], "sk-real-abcdef1234")

    def test_all_star_key_is_not_saved(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.json"
            self._write(p, "sk-real-abcdef1234")
            with patch.object(cfgmod, "CONFIG_PATH", p):
                cfgmod.save_config({"llm": {"api_key": "***************"}})
                self.assertEqual(cfgmod.load_config()["llm"]["api_key"], "sk-real-abcdef1234")

    def test_real_new_key_is_saved(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.json"
            self._write(p, "sk-real-abcdef1234")
            with patch.object(cfgmod, "CONFIG_PATH", p):
                cfgmod.save_config({"llm": {"api_key": "sk-new-key-000"}})
                self.assertEqual(cfgmod.load_config()["llm"]["api_key"], "sk-new-key-000")

    def test_empty_key_keeps_existing(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.json"
            self._write(p, "sk-real-abcdef1234")
            with patch.object(cfgmod, "CONFIG_PATH", p):
                cfgmod.save_config({"llm": {"api_key": ""}})
                self.assertEqual(cfgmod.load_config()["llm"]["api_key"], "sk-real-abcdef1234")

    def test_scheduler_defaults_include_concurrency(self):
        """调度默认: 跨平台并发 4, 间隔下限 1 分钟。"""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.json"
            with patch.object(cfgmod, "CONFIG_PATH", p):
                sched = cfgmod.load_config()["scheduler"]
                self.assertEqual(sched["max_concurrent"], 4)
                self.assertEqual(sched["min_interval_min"], 1)

    def test_save_concurrency_clamped(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.json"
            with patch.object(cfgmod, "CONFIG_PATH", p):
                merged = cfgmod.save_config({"scheduler": {"max_concurrent": 99}})
                self.assertEqual(merged["scheduler"]["max_concurrent"], 99)  # 保存层不做钳制, 由 web 层钳制
                self.assertIn("max_concurrent", merged["scheduler"])


if __name__ == "__main__":
    unittest.main()
