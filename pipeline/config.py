# -*- coding: utf-8 -*-
"""应用配置: LLM 接入与调度风控参数。

配置保存在 BASE_DIR/data/config.json(本机私有, 不进打包 zip)。
未配置时使用 DEFAULT_CONFIG 兜底。
"""
from __future__ import annotations

import json
from pathlib import Path

from pipeline.store import DATA_DIR

CONFIG_PATH = DATA_DIR / "config.json"

DEFAULT_CONFIG = {
    "llm": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "model": "deepseek-chat",
        "timeout": 60,
        "max_tokens": 2048,
        "temperature": 1.0,
        "n_candidates": 3,
    },
    "scheduler": {
        "interval_min": 5,          # 每条发布之间最小间隔(分钟, 同平台同账号)
        "daily_cap": 25,            # 每账号每日发布上限(未单独配置平台时的兜底值)
        "max_concurrent": 4,        # 跨平台并发上传数(不同平台同时开, 同平台同账号仍串行)
        "platform_daily_caps": {    # 各平台每日上限(风控建议值, 可调)
            "douyin": 3,
            "kuaishou": 10,
            "xiaohongshu": 3,
            "tencent": 5,
        },
        "min_interval_min": 1,      # 允许设置的最小间隔
        "max_interval_min": 60,
        "min_daily_cap": 1,
        "max_daily_cap": 100,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        if CONFIG_PATH.is_file():
            user_cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(user_cfg, dict):
                cfg = _deep_merge(cfg, user_cfg)
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg: dict) -> dict:
    """整体保存(与默认合并后落盘), 返回合并结果。
    防护: api_key 含掩码字符(*)时视为"未修改", 保留原 Key, 防止把脱敏值写回覆盖真实 Key。
    """
    prev = load_config()
    merged = _deep_merge(prev, cfg)
    new_key = str(merged["llm"].get("api_key") or "")
    if not new_key or "*" in new_key:  # 空值/掩码值均视为"未修改", 保留原 Key
        merged["llm"]["api_key"] = str(prev["llm"].get("api_key") or "")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return merged


def get_llm_config() -> dict:
    return load_config()["llm"]


def get_scheduler_config() -> dict:
    return load_config()["scheduler"]


def mask_key(key: str) -> str:
    """API Key 脱敏: 仅显示后 4 位。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return "*" * (len(key) - 4) + key[-4:]
