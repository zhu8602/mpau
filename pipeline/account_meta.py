# -*- coding: utf-8 -*-
"""登录账号的真实昵称元数据(仅用于展示, 与 Cookie 文件解耦)。

登录成功后由各平台上传器抓取平台真实昵称写入:
    DATA_DIR/accounts.json: {"douyin": {"1144": {"nickname": "冰绮z", "updated_at": "..."}}}
别名(account)仍是主键(Cookie 文件名/命令行参数), 昵称只是展示信息, 可随时刷新。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from pipeline.store import DATA_DIR

META_PATH = DATA_DIR / "accounts.json"


def load_meta() -> dict:
    try:
        if META_PATH.is_file():
            data = json.loads(META_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, ValueError):
        pass
    return {}


def normalize_legacy_keys() -> None:
    """把 0.1.0 及更早版本误用 Cookie 文件 stem(douyin_douyin1)写入的键迁移为别名(douyin1)。

    读取路径全部经过这里做惰性迁移; 已有别名键优先(更新鲜)。有改动才写盘。
    """
    meta = load_meta()
    changed = False
    for platform, entries in list(meta.items()):
        if not isinstance(entries, dict):
            continue
        prefix = f"{platform}_"
        for key in list(entries.keys()):
            if key.startswith(prefix) and len(key) > len(prefix):
                alias = key[len(prefix):]
                if alias not in entries:
                    entries[alias] = entries[key]
                del entries[key]
                changed = True
    if changed:
        save_meta(meta)


def save_meta(meta: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _normalize_account(platform: str, account: str) -> str:
    """归一化账号键: 容忍传入 Cookie 文件 stem(如 douyin_douyin1), 统一剥成别名(douyin1)。

    别名是展示与查询的主键(web/app.py list_accounts 返回别名); 上传器侧常顺手传
    Path(account_file).stem, 不归一化会导致 nicknames 的键永远和前端对不上。
    """
    prefix = f"{platform}_"
    if account.startswith(prefix) and len(account) > len(prefix):
        return account[len(prefix):]
    return account


def set_nickname(platform: str, account: str, nickname: str) -> None:
    """记录/更新某账号的平台真实昵称(空昵称不写)。"""
    nickname = (nickname or "").strip()
    if not nickname:
        return
    account = _normalize_account(platform, account)
    meta = load_meta()
    entry = meta.setdefault(platform, {})
    entry[account] = {"nickname": nickname, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    save_meta(meta)


def nicknames_for(platform: str) -> dict[str, str]:
    """返回 {account: nickname}。"""
    return {
        acc: str(info.get("nickname") or "")
        for acc, info in (load_meta().get(platform) or {}).items()
        if isinstance(info, dict)
    }


def remove_nickname(platform: str, account: str) -> None:
    """删除某账号的昵称元数据(退出账号时调用), 不存在则忽略。"""
    account = _normalize_account(platform, account)
    meta = load_meta()
    entry = meta.get(platform)
    if isinstance(entry, dict) and account in entry:
        entry.pop(account, None)
        if not entry:
            meta.pop(platform, None)
        save_meta(meta)


def nickname_for(platform: str, account: str) -> str:
    return str((load_meta().get(platform) or {}).get(account, {}).get("nickname") or "")
