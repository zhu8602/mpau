# -*- coding: utf-8 -*-
"""平台文案规则与校验器。

规则数据: pipeline/data/copy_rules.json(每平台: 字数上限/风格/违禁词/挂载字段)。
校验分级:
  - level "error"  : 硬性违规(字数超限), 生成候选被剔除
  - level "warning": 风险提示(违禁词等), 保留候选但 UI 标黄提醒
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_RULES_PATH = Path(__file__).resolve().parent / "data" / "copy_rules.json"

CORE_PLATFORMS = ["douyin", "kuaishou", "tencent", "xiaohongshu"]

with _RULES_PATH.open(encoding="utf-8") as _f:
    RULES: dict[str, dict[str, Any]] = json.load(_f)

_FALLBACK_RULE: dict[str, Any] = {
    "cn": "其他平台",
    "title_max": 50,
    "desc_max": 500,
    "title_style": "突出卖点、口语化",
    "desc_style": "补充细节",
    "tag_style": "2-4 个话题词，不带 #",
    "banned": [],
    "goods": None,
    "notes": "",
}


def rule_for(platform: str) -> dict[str, Any]:
    rule = RULES.get(platform)
    if not rule:
        return dict(_FALLBACK_RULE)
    merged = dict(_FALLBACK_RULE)
    merged.update(rule)
    return merged


def platform_cn(platform: str) -> str:
    return rule_for(platform)["cn"]


def clean_tags(tags: Any) -> list[str]:
    """标签清洗: 支持字符串(逗号/空格/# 分隔)或列表; 去重去空去 #。"""
    if not tags:
        return []
    if isinstance(tags, str):
        raw = re.split(r"[,\s#]+", tags)
    else:
        raw = [str(t) for t in tags]
    seen: list[str] = []
    for item in raw:
        tag = item.strip().lstrip("#").strip()
        if tag and tag not in seen and len(tag) <= 20:
            seen.append(tag)
    return seen


def validate_title(platform: str, title: str) -> list[dict]:
    """校验标题, 返回 issues 列表。title 为空返回空列表(由上层判必填)。"""
    title = (title or "").strip()
    if not title:
        return []
    rule = rule_for(platform)
    issues: list[dict] = []
    length = len(title)
    title_max = int(rule.get("title_max") or 0)
    title_min = int(rule.get("title_min") or 0)
    if title_max and length > title_max:
        issues.append({"level": "error", "msg": f"标题 {length} 字, 超过 {rule['cn']} 上限 {title_max} 字"})
    if title_min and length < title_min:
        issues.append({"level": "error", "msg": f"标题 {length} 字, 少于 {rule['cn']} 下限 {title_min} 字"})
    for word in rule.get("banned") or []:
        if word and word in title:
            issues.append({"level": "warning", "msg": f"含违禁词/极限词「{word}」, 有审核风险"})
    return issues


def validate_short_title(title: str) -> list[dict]:
    """视频号短标题校验(≤16 字)。"""
    title = (title or "").strip()
    if not title:
        return []
    if len(title) > 16:
        return [{"level": "error", "msg": f"短标题 {len(title)} 字, 超过 16 字上限"}]
    return []


def validate_candidate(platform: str, cand: dict) -> list[dict]:
    """校验一个候选(标题+短标题), 汇总 issues。"""
    issues = validate_title(platform, cand.get("title", ""))
    if platform == "tencent" and cand.get("short_title"):
        issues += validate_short_title(cand["short_title"])
    if platform in ("douyin",) and cand.get("product_title"):
        if len(str(cand["product_title"]).strip()) > 10:
            issues.append({"level": "warning", "msg": "商品短标题建议 10 字内"})
    return issues
