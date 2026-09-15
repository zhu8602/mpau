# -*- coding: utf-8 -*-
"""系统托盘常驻: 安装版由启动器以 MPAU_TRAY=1 拉起时, 在托盘提供「打开主界面 / 退出」。

仅在 Windows 安装版启用; pystray 或图标文件不可用时静默降级(不启托盘, 主服务照常)。
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable


def start_tray(open_ui: Callable[[], None], on_exit: Callable[[], None],
               icon_path: Path, title: str = "mpau 发布台") -> bool:
    """在守护线程中启动托盘图标。启动失败返回 False。"""
    try:
        import pystray
        from PIL import Image
    except ImportError:
        return False
    if not Path(icon_path).is_file():
        return False

    image = Image.open(icon_path)

    def _open(icon, _item):
        open_ui()

    def _quit(icon, _item):
        icon.stop()
        on_exit()

    icon = pystray.Icon(
        "mpau",
        image,
        title,
        menu=pystray.Menu(
            pystray.MenuItem("打开主界面", _open, default=True),
            pystray.MenuItem("退出 mpau", _quit),
        ),
    )
    threading.Thread(target=icon.run, daemon=True).start()
    return True
