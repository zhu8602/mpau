# -*- coding: utf-8 -*-
"""计划器: 平台能力定义 + 上传命令构建 + 1 视频 × N 平台展开。

PLATFORM_OPTS 是唯一权威定义(web/app.py 从本模块导入),
保证 Web 表单、批量引擎、CLI 三处构建命令逻辑一致。
"""
from __future__ import annotations

import json
from typing import Any

from pipeline import rules

PLATFORMS = [
    "douyin", "kuaishou", "xiaohongshu", "tencent",
    "pdd", "tmall", "jd", "baijiahao",
    "tiktok",
]

PLATFORM_OPTS: dict[str, dict[str, Any]] = {
    "douyin": {"note": True, "goods": "product", "dry_run": True},
    # 快手: 走「作者服务 → 关联商品」, **只支持按商品名称**关联(无商品ID) —— 见
    # ks_uploader._add_goods 的真机校准注释。goods_name 经 --goods-name 传给 CLI。
    "kuaishou": {"note": True, "goods": "goods_name", "dry_run": False},
    "xiaohongshu": {"note": True, "goods": None, "dry_run": False},
    "tencent": {"note": False, "goods": "goods_id", "dry_run": False, "draft": True},
    "pdd": {"note": False, "goods": "goods_id", "dry_run": True, "desc_required": True},
    "tmall": {"note": False, "goods": "goods_id", "dry_run": True, "title_required": True},
    "jd": {"note": False, "goods": "goods_id", "dry_run": True, "title_required": True},
    "baijiahao": {"note": False, "goods": None, "title_required": True},
    # TikTok: 只有标题+话题(无描述字段), 无商品/无试跑/无草稿; 定时为 5 分钟粒度
    "tiktok": {
        "note": False, "goods": None, "title_required": True,
        "tag_required": True, "no_desc": True,
    },
}


def build_upload_cmd(
    platform: str,
    account: str,
    file_path: str,
    *,
    title: str = "",
    desc: str = "",
    tags: list[str] | None = None,
    schedule: str = "",
    thumbnail: str = "",
    product_link: str = "",
    product_title: str = "",
    goods_id: str = "",
    goods_name: str = "",
    draft: bool = False,
    dry_run: bool = False,
    headless: bool = False,
    debug: bool = False,
) -> list[str]:
    """按平台能力拼 mpau upload-video 命令(与既有单发表单逻辑对齐)。"""
    opts = PLATFORM_OPTS[platform]
    cmd = [platform, "upload-video", "--account", account, "--file", file_path]
    if title:
        cmd += ["--title", title]
    # 平台无描述字段(TikTok)时不追加 --desc, 否则 CLI 会 argparse 报错
    if desc and not opts.get("no_desc"):
        cmd += ["--desc", desc]
    tags = rules.clean_tags(tags)
    if tags:
        cmd += ["--tags", ",".join(tags)]
    if schedule:
        cmd += ["--schedule", schedule]
    if thumbnail:
        cmd += ["--thumbnail", thumbnail]
    goods = opts.get("goods")
    if goods == "product":
        if product_link:
            cmd += ["--product-link", product_link]
        if product_title:
            cmd += ["--product-title", product_title]
    elif goods == "goods_id":
        if goods_id:
            cmd += ["--goods-id", str(goods_id)]
    elif goods == "goods_name":
        if goods_name:
            cmd += ["--goods-name", str(goods_name)]
    if opts.get("draft") and draft:
        cmd.append("--draft")
    if opts.get("dry_run") and dry_run:
        cmd.append("--dry-run")
    if headless:
        cmd.append("--headless")
    else:
        cmd.append("--headed")
    if debug:
        cmd.append("--debug")
    return cmd


def parse_account_map(raw: str) -> dict[str, list[str]]:
    """解析 "douyin:shop1,tencent:shop1" 形式的账号映射(每平台可为多账号)。"""
    mapping: dict[str, list[str]] = {}
    if not raw:
        return mapping
    for part in raw.split(","):
        part = part.strip()
        if ":" not in part:
            continue
        key, value = part.split(":", 1)
        key, value = key.strip(), value.strip()
        if key and value:
            mapping.setdefault(key, []).append(value)
    return mapping


def expand_items(
    video: dict[str, Any],
    platforms: list[str],
    account_map: dict[str, Any],
    copy_map: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """1 视频 × N 平台 × M 账号 → 条目草稿(多账号多样化发布)。

    account_map: {platform: [account, ...]}(多账号) 或 {platform: "account"}(旧单账号, 兼容)。
    某平台未配置账号时生成 1 条 needs_manual 占位(提示未选择账号)。
    copy_map: {platform: {"title": ..., "desc": ..., "tags": [...]}} 可预先指定文案;
             为 None 时 item 文案留空(待生成)。
    """
    items: list[dict[str, Any]] = []
    goods = {}
    raw_goods = video.get("goods_json")
    if isinstance(raw_goods, str):
        try:
            goods = json.loads(raw_goods)
        except ValueError:
            goods = {}
    elif isinstance(raw_goods, dict):
        goods = raw_goods

    for platform in platforms:
        if platform not in PLATFORMS:
            continue
        raw_accounts = account_map.get(platform, [])
        if isinstance(raw_accounts, str):
            raw_accounts = [raw_accounts] if raw_accounts else []
        accounts = [str(a) for a in raw_accounts if a]
        if not accounts:
            accounts = [""]  # 占位: 未选择账号
        for account in accounts:
            chosen = (copy_map or {}).get(platform, {}) if copy_map else {}
            item = {
                "video_id": int(video["id"]),
                "platform": platform,
                "account": account,
                "title": str(chosen.get("title") or "").strip(),
                "desc": str(chosen.get("desc") or "").strip(),
                "tags": ",".join(rules.clean_tags(chosen.get("tags"))),
                "schedule": video.get("schedule") or "",
                "goods_json": json.dumps(goods, ensure_ascii=False),
                "status": "draft" if account else "needs_manual",
                "error": "" if account else "未选择该平台账号",
            }
            items.append(item)
    return items


def public_item(item: dict[str, Any], video: dict[str, Any] | None = None) -> dict[str, Any]:
    """对外返回的 item 视图: 附带平台中文名/视频路径/标题。"""
    out = dict(item)
    out["platform_cn"] = rules.platform_cn(item.get("platform", ""))
    out["video_path"] = (video or {}).get("path", "")
    out["video_title"] = (video or {}).get("base_title", "")
    out["sha256"] = (video or {}).get("sha256", "")
    return out
