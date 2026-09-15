# -*- coding: utf-8 -*-
"""mpau 发布台启动器(安装版双击入口, 仅用标准库, 可被 PyInstaller 冻结为 exe)。

布局约定(安装目录):
  mpau发布台.exe        <- 本启动器
  app/                  项目源码(web/app.py 等)
  python/               内置 Python(依赖已预装)
数据目录: %LOCALAPPDATA%\\mpau-data(可用环境变量 MPAU_HOME 覆盖, 便携模式用)

行为: 后台已在运行则直接唤起主界面; 否则拉起 web 服务, 等端口就绪后由服务端用内置
Chromium 以 app 窗口打开界面(不依赖系统默认浏览器), 失败时回退默认浏览器。
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import traceback
import urllib.request
from pathlib import Path

PORT = int(os.getenv("MPAU_WEB_PORT", "8898"))
HOST = "127.0.0.1"
BASE_URL = f"http://{HOST}:{PORT}"


def install_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def data_home() -> Path:
    home = (os.environ.get("MPAU_HOME") or "").strip()
    if home:
        return Path(home)
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "mpau-data"


def log_line(home: Path, text: str) -> None:
    try:
        log_dir = home / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "launcher.log", "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
    except OSError:
        pass


def error_box(title: str, message: str) -> None:
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)  # MB_ICONERROR
    except Exception:  # noqa: BLE001
        print(f"{title}: {message}")


def server_up() -> bool:
    try:
        with urllib.request.urlopen(f"{BASE_URL}/login", timeout=2) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001
        return False


def wait_ready(timeout: float = 90.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if server_up():
            return True
        time.sleep(0.8)
    return False


def read_token(home: Path) -> str:
    token_file = home / "data" / "web_token.txt"
    for _ in range(20):  # 服务刚就绪时令牌文件可能还没写盘
        try:
            token = token_file.read_text(encoding="utf-8").strip()
            if token:
                return token
        except OSError:
            pass
        time.sleep(0.5)
    return ""


def open_ui_via_server(token: str) -> bool:
    """让服务端打开主界面(内置 Chromium app 窗口)。老版本后台无此接口时返回 False。"""
    try:
        req = urllib.request.Request(
            f"{BASE_URL}/api/open-ui", data=b"", method="POST",
            headers={"X-MPAU-Token": token},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    root = install_root()
    home = data_home()
    home.mkdir(parents=True, exist_ok=True)
    log_line(home, f"launcher start, root={root}, home={home}")

    if not server_up():
        pythonw = root / "python" / "pythonw.exe"
        app_py = root / "app" / "web" / "app.py"
        if not pythonw.is_file():  # 开发环境兜底: 用当前解释器
            pythonw = Path(sys.executable)
        if not app_py.is_file():
            error_box("mpau 发布台", f"找不到服务入口:\n{app_py}\n\n安装包可能损坏, 请重新安装。")
            return 1
        env = os.environ.copy()
        env["MPAU_HOME"] = str(home)
        env["MPAU_WEB_HOST"] = HOST
        env["MPAU_WEB_PORT"] = str(PORT)
        env["MPAU_TRAY"] = "1"  # 启用系统托盘(右键: 打开主界面/退出)
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
            subprocess.Popen(
                [str(pythonw), str(app_py)],
                cwd=str(app_py.parent.parent),
                env=env,
                creationflags=creationflags,
                close_fds=True,
            )
        except OSError as exc:
            log_line(home, f"spawn failed: {exc}")
            error_box("mpau 发布台", f"启动后台服务失败:\n{exc}")
            return 1
        log_line(home, "server spawning, waiting for port")
        if not wait_ready():
            log_line(home, "wait_ready timeout")
            error_box("mpau 发布台", "后台服务启动超时。\n可查看日志: " + str(home / "logs"))
            return 1

    token = read_token(home)
    url = f"{BASE_URL}/?token={token}" if token else BASE_URL
    # 优先让服务端用内置 Chromium 以 app 窗口打开; 失败(老版本后台等)回退系统默认浏览器
    if token and open_ui_via_server(token):
        log_line(home, "open ui: via server (bundled chromium app window)")
        return 0
    log_line(home, f"open ui fallback: default browser {BASE_URL}")
    try:
        os.startfile(url)  # noqa: S606 - 本机默认浏览器打开固定本地地址
    except OSError as exc:
        error_box("mpau 发布台", f"后台已启动, 但打开浏览器失败: {exc}\n请手动访问 {url}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # noqa: BLE001
        tb = traceback.format_exc()
        try:
            log_line(data_home(), tb)
        except Exception:  # noqa: BLE001
            pass
        error_box("mpau 发布台", f"启动器异常:\n{tb[-800:]}")
        raise SystemExit(1)
