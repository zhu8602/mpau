# -*- coding: utf-8 -*-
"""回归测试: 浏览器选择探测(utils.config.resolve_chrome_path)。

优先级: 显式 MPAU_CHROME_PATH > 系统 Google Chrome(返回空串走 channel=chrome) > 内置内核兜底。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["MPAU_DATA_DIR"] = tempfile.mkdtemp(prefix="mpau-test-")

from utils.config import resolve_chrome_path


def _fake_env(**kw) -> dict:
    """每个测试独立的假环境, 避免真机/历史残留干扰。"""
    base = tempfile.mkdtemp(prefix="mpau-pf-")
    env = {
        "LOCALAPPDATA": tempfile.mkdtemp(prefix="mpau-la-"),
        "ProgramFiles": os.path.join(base, "pf"),
        "ProgramFiles(x86)": os.path.join(base, "pf86"),
    }
    env.update(kw)
    return env


class TestResolveChromePath(unittest.TestCase):
    def test_explicit_env_wins(self):
        env = _fake_env()
        self.assertEqual(
            resolve_chrome_path({**env, "MPAU_CHROME_PATH": r"D:\my\chrome.exe"}),
            r"D:\my\chrome.exe",
        )

    def test_system_chrome_keeps_empty(self):
        """有系统 Chrome 时返回空串, uploader 维持 channel="chrome"。"""
        env = _fake_env()
        chrome = Path(env["ProgramFiles"]) / "Google" / "Chrome" / "Application" / "chrome.exe"
        chrome.parent.mkdir(parents=True, exist_ok=True)
        chrome.write_text("x")
        self.assertEqual(resolve_chrome_path(env), "")

    def test_system_chrome_x86_path(self):
        env = _fake_env()
        chrome = Path(env["ProgramFiles(x86)"]) / "Google" / "Chrome" / "Application" / "chrome.exe"
        chrome.parent.mkdir(parents=True, exist_ok=True)
        chrome.write_text("x")
        self.assertEqual(resolve_chrome_path(env), "")

    def test_bundled_kernel_fallback(self):
        """无系统 Chrome 时回退到 ms-playwright 内置内核(选最新 build)。"""
        env = _fake_env()
        la = Path(env["LOCALAPPDATA"])
        old = la / "ms-playwright" / "chromium-1208" / "chrome-win64" / "chrome.exe"
        new = la / "ms-playwright" / "chromium-1234" / "chrome-win64" / "chrome.exe"
        old.parent.mkdir(parents=True, exist_ok=True)
        old.write_text("x")
        new.parent.mkdir(parents=True, exist_ok=True)
        new.write_text("x")
        self.assertEqual(resolve_chrome_path(env), str(new))

    def test_no_browser_returns_empty(self):
        env = _fake_env()
        self.assertEqual(resolve_chrome_path(env), "")

    def test_bundled_kernel_used_when_programfiles_missing(self):
        """ProgramFiles 环境变量缺失时也不报错, 直接走内置内核。"""
        env = _fake_env()
        env.pop("ProgramFiles")
        env.pop("ProgramFiles(x86)")
        la = Path(env["LOCALAPPDATA"])
        exe = la / "ms-playwright" / "chromium-1208" / "chrome-win64" / "chrome.exe"
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_text("x")
        self.assertEqual(resolve_chrome_path(env), str(exe))


class TestUploaderChromeFallback(unittest.TestCase):
    """回归护栏: 任何 uploader 使用 channel="chrome" 时, 同文件必须有 LOCAL_CHROME_PATH 兜底分支。

    曾发生: douyin_uploader 4 处 launch 写死 channel="chrome", 无 Chrome 的机器登录直接失败。
    """

    def test_every_channel_chrome_has_fallback(self):
        root = Path(__file__).resolve().parents[1]
        uploaders = sorted((root / "uploader").glob("*/main*.py"))
        self.assertTrue(uploaders, "未找到 uploader 文件")
        for f in uploaders:
            src = f.read_text(encoding="utf-8")
            if 'channel="chrome"' in src or "channel='chrome'" in src:
                self.assertIn(
                    "LOCAL_CHROME_PATH",
                    src,
                    f"{f.name}: 使用 channel=chrome 但缺少 LOCAL_CHROME_PATH 兜底,"
                    " 无 Chrome 的机器将无法登录/发布",
                )


if __name__ == "__main__":
    unittest.main()
