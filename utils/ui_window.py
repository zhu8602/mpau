# -*- coding: utf-8 -*-
"""以内置 Chromium 的 --app 模式打开 Web 管理界面; 内核缺失时回退系统默认浏览器。

为什么不用用户默认浏览器: 部分国产浏览器会吃掉 URL 里的 ?token=, 或用老内核渲染导致
Vue3 白屏。安装包已随附 Chromium 内核(与上传器共用 %LOCALAPPDATA%/ms-playwright),
UI 窗口用独立的 ui-profile 目录, 不碰用户浏览器配置; Cookie 持久化, 第二次打开免 token。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from utils.config import MPAU_HOME, bundled_chromium_path

WINDOW_SIZE = "1520,950"


def open_main_window(url: str) -> tuple[str, subprocess.Popen | None]:
    """打开主界面。

    返回 (mode, proc): mode 为 "chromium-app"(内置内核 app 窗口, proc 为句柄,
    退出服务时应一并关闭)或 "default-browser"(系统默认浏览器, proc 为 None)。
    """
    exe = bundled_chromium_path()
    if exe:
        try:
            profile = Path(MPAU_HOME) / "ui-profile"
            profile.mkdir(parents=True, exist_ok=True)
            proc = subprocess.Popen(
                [
                    exe,
                    f"--app={url}",
                    f"--user-data-dir={profile}",
                    # 沙箱在部分机器上初始化失败会导致进程静默退出(exit 3), 与上传器保持一致关掉
                    "--no-sandbox",
                    # Chrome for Testing 会常驻"仅适用于自动测试"提示条, test-type=gpu 实测可隐藏
                    "--test-type=gpu",
                    "--no-first-run",
                    "--no-default-browser-check",
                    f"--window-size={WINDOW_SIZE}",
                    # 默认最大化打开; window-size 作为用户取消最大化后的还原尺寸
                    "--start-maximized",
                ],
                close_fds=True,
            )
            return "chromium-app", proc
        except OSError:
            pass  # 内核损坏等: 落回默认浏览器
    os.startfile(url)  # noqa: S606 - 本机默认浏览器打开固定本地地址
    return "default-browser", None
