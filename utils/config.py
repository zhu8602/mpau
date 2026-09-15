from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
# 可写数据根目录(cookies/data/logs 的父级): 默认代码目录; 安装版由启动器设为 %LOCALAPPDATA%\mpau-data
MPAU_HOME = Path(os.getenv("MPAU_HOME", str(BASE_DIR)))
COOKIES_DIR = MPAU_HOME / "cookies"
LOCAL_CHROME_HEADLESS = os.getenv("MPAU_HEADLESS", "true").strip().lower() not in {"0", "false", "no", "off"}
DEBUG_MODE = os.getenv("MPAU_DEBUG", "true").strip().lower() not in {"0", "false", "no", "off"}


def _system_chrome_candidates(env: dict | None = None) -> list[str]:
    """Windows 上 Google Chrome 的标准安装路径。"""
    env = env or os.environ
    out: list[str] = []
    for key in ("ProgramFiles", "ProgramFiles(x86)"):
        base = env.get(key, "")
        if base:
            out.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    return out


def _bundled_chromium(env: dict | None = None) -> str:
    """%LOCALAPPDATA%/ms-playwright 下找内置 chromium 内核(安装包随附, 兜底用)。

    返回 chrome.exe 绝对路径; 找不到返回空串。
    """
    env = env or os.environ
    base = Path(env.get("LOCALAPPDATA", "")) / "ms-playwright"
    if not base.is_dir():
        return ""
    try:
        for d in sorted(base.glob("chromium-*"), reverse=True):
            exe = d / "chrome-win64" / "chrome.exe"
            if exe.is_file():
                return str(exe)
    except OSError:
        pass
    return ""


def bundled_chromium_path(env: dict | None = None) -> str:
    """内置 Chromium 内核路径(无论是否存在系统 Chrome); 找不到返回空串。

    供 UI 窗口(utils/ui_window.py)使用: 界面展示要行为可控, 不依赖用户机器装了什么浏览器。
    """
    return _bundled_chromium(env)


def resolve_chrome_path(env: dict | None = None) -> str:
    """浏览器选择: 显式配置 > 系统 Google Chrome(保持 channel=chrome 现状) > 内置内核兜底。

    - 返回非空: uploader 会走 executable_path 分支(用该浏览器);
    - 返回空串: uploader 走 channel="chrome"(Playwright 自动找系统 Chrome)。
    """
    env = env or os.environ
    explicit = env.get("MPAU_CHROME_PATH", "").strip()
    if explicit:
        return explicit
    if any(os.path.isfile(p) for p in _system_chrome_candidates(env)):
        return ""  # 有系统 Chrome: 维持 channel="chrome"(风控表现最好)
    return _bundled_chromium(env)


# 模块加载时解析一次, 供所有 uploader / browser_hook 使用
LOCAL_CHROME_PATH = resolve_chrome_path()
