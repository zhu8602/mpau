# -*- coding: utf-8 -*-
"""mpau 子进程执行器(web 任务队列与批量调度共用)。

统一: venv 内 mpau.exe、cwd=项目根、UTF-8、Windows 无窗口、逐行回传日志。
"""
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from utils.config import BASE_DIR

VENV_MPAU = BASE_DIR / ".venv" / "Scripts" / "mpau.exe"


def mpau_cmd(cmd: list[str]) -> list[str]:
    """拼装 mpau 调用命令: 开发环境用 venv 里的 mpau.exe; 打包版(无 venv)用当前解释器跑源码入口。"""
    if VENV_MPAU.exists():
        return [str(VENV_MPAU)] + [str(c) for c in cmd]
    return [sys.executable, str(BASE_DIR / "mpau_cli.py")] + [str(c) for c in cmd]


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def spawn_mpau(cmd: list[str], extra_env: dict[str, str] | None = None) -> subprocess.Popen:
    """启动 mpau 子进程(非阻塞), 返回 Popen。启动失败抛 RuntimeError。"""
    env = _base_env()
    if extra_env:
        env.update(extra_env)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        return subprocess.Popen(
            mpau_cmd(cmd),
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=creationflags,
            bufsize=1,
        )
    except OSError as exc:
        raise RuntimeError(f"无法启动 mpau: {exc}") from exc


def stream_mpau(proc: subprocess.Popen, log_cb: Callable[[str], None] | None = None) -> int:
    """消费子进程输出并等待结束, 返回退出码。"""
    for line in proc.stdout:
        if log_cb:
            try:
                log_cb(line.rstrip())
            except Exception:  # noqa: BLE001
                pass
    proc.wait()
    return proc.returncode


def execute_mpau(
    cmd: list[str],
    log_cb: Callable[[str], None] | None = None,
    extra_env: dict[str, str] | None = None,
) -> int:
    """同步执行 mpau 子进程, 逐行回调日志, 返回退出码。"""
    return stream_mpau(spawn_mpau(cmd, extra_env), log_cb)


def kill_by_pid(pid: int) -> None:
    """Windows 下整树结束指定 PID 的进程。"""
    if pid <= 0:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        try:
            os.kill(pid, 9)
        except OSError:
            pass
