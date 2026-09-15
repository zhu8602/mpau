# -*- coding: utf-8 -*-
"""批量发布编排: 扫描/导入 → 填标题 → 生成文案 → 计划 → 审阅 → 运行 → 报告。

Web(/api/batch/*)与 CLI(mpau batch ...)共用; CLI 入口为 dispatch_batch()。
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any

from pipeline import copy_engine, planner, rules, scanner, scheduler, store

BATCH_CSV_COLUMNS = [
    "平台", "账号", "文件名", "标题", "描述", "标签",
    "定时发布时间", "状态", "失败原因", "发布时间",
]


def new_batch_id() -> str:
    return "b" + time.strftime("%Y%m%d-%H%M%S")


# ---------------------------------------------------------------------------
# 扫描 / 导入 / 填标题
# ---------------------------------------------------------------------------
def scan_and_register(root: str, batch_id: str | None = None) -> dict[str, Any]:
    """扫描目录并把视频写入 videos 表(sha256 仅对缺失的懒计算)。
    同时登记本批次视频清单, 实现"一批 = 一个文件夹"的隔离。"""
    batch_id = batch_id or new_batch_id()
    found = scanner.scan_dir(root)
    if not found:
        raise RuntimeError(f"目录里没有找到视频文件: {root}")
    videos = []
    for item in found:
        existing = store.get_video_by_path(item["path"])
        if existing:
            videos.append(existing)
            continue
        sha = store.sha256_file(item["path"])
        video_id = store.upsert_video(
            item["path"],
            sha256=sha,
            size=item["size"],
            base_title=item["base_title"],
            base_desc=item["base_desc"],
            base_tags=item["base_tags"],
            goods_json=item["goods_json"],
            schedule=item["schedule"],
            cover=item["cover"],
        )
        videos.append(store.get_video(video_id))
    store.set_batch_videos(batch_id, [v["id"] for v in videos])
    return {"batch_id": batch_id, "videos": videos}


def import_and_register(csv_path: str, batch_id: str | None = None) -> dict[str, Any]:
    batch_id = batch_id or new_batch_id()
    rows = scanner.import_csv(csv_path)
    if not rows:
        raise RuntimeError(f"CSV 中没有可用的视频行: {csv_path}")
    videos = []
    for item in rows:
        existing = store.get_video_by_path(item["path"])
        if existing:
            videos.append(existing)
            continue
        sha = store.sha256_file(item["path"])
        video_id = store.upsert_video(
            item["path"],
            sha256=sha,
            size=item["size"],
            base_title=item["base_title"],
            base_desc=item["base_desc"],
            base_tags=item["base_tags"],
            goods_json=item["goods_json"],
            schedule=item["schedule"],
            cover=item["cover"],
        )
        videos.append(store.get_video(video_id))
    store.set_batch_videos(batch_id, [v["id"] for v in videos])
    return {"batch_id": batch_id, "videos": videos}


def add_video_and_register(path: str, batch_id: str | None = None) -> dict[str, Any]:
    """登记单个视频到批次(单条发布 = 单视频批次)。

    文件校验 + upsert(含 sidecar 元数据) + 追加到批次清单(按视频 id 去重)。
    batch_id 为空时新建批次; added=False 表示该视频已在本批次(不重复登记)。
    """
    video_path = Path(path)
    if not video_path.is_file():
        raise FileNotFoundError(f"视频文件不存在: {video_path}")
    if not scanner.is_video_file(video_path):
        raise RuntimeError(f"不是支持的视频文件: {video_path.name}")
    batch_id = batch_id or new_batch_id()
    existing = store.get_video_by_path(str(video_path))
    if existing:
        video = existing
    else:
        meta = scanner.video_meta(video_path)
        video_id = store.upsert_video(
            meta["path"],
            sha256=store.sha256_file(meta["path"]),
            size=meta["size"],
            base_title=meta["base_title"],
            base_desc=meta["base_desc"],
            base_tags=meta["base_tags"],
            goods_json=meta["goods_json"],
            schedule=meta["schedule"],
            cover=meta["cover"],
        )
        video = store.get_video(video_id) or {}
    ids = store.get_batch_videos(batch_id)
    if video.get("id") in ids:
        return {"batch_id": batch_id, "video": video, "added": False}
    store.set_batch_videos(batch_id, ids + [video["id"]])
    return {"batch_id": batch_id, "video": video, "added": True}


def update_video_fields(video_id: int, fields: dict[str, Any]) -> dict:
    allowed = {
        "base_title": str, "base_desc": str, "base_tags": str,
        "schedule": str, "cover": str, "goods_json": str,
    }
    cleaned = {}
    for key, cast in allowed.items():
        if key in fields and fields[key] is not None:
            cleaned[key] = cast(fields[key])
    store.update_video(video_id, **cleaned)
    return store.get_video(video_id) or {}


# ---------------------------------------------------------------------------
# 计划 / 生成 / 审阅
# ---------------------------------------------------------------------------
def plan_batch(
    batch_id: str,
    video_ids: list[int],
    platforms: list[str],
    account_map: dict[str, Any],
    copy_map: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """为每个视频 × 平台 × 账号创建草稿条目; 已存在的条目只更新账号, 不重复创建。

    account_map: {platform: [account, ...]} 多账号多样化发布; 值也兼容单账号字符串。
    """
    created = 0
    updated = 0
    for video_id in video_ids:
        video = store.get_video(video_id)
        if not video:
            continue
        per_video_copy = (copy_map or {}).get(video_id)
        for item in planner.expand_items(video, platforms, account_map, per_video_copy):
            existing = store.item_exists(batch_id, video_id, item["platform"], item["account"])
            if existing:
                if existing["account"] != item["account"] and item["account"]:
                    store.update_item(existing["id"], account=item["account"])
                    updated += 1
                continue
            store.create_item(batch_id=batch_id, **item)
            created += 1
    return {"batch_id": batch_id, "created": created, "updated": updated}


def generate_batch(
    batch_id: str,
    platforms: list[str] | None = None,
    *,
    with_desc: bool = True,
    with_tags: bool = True,
    with_goods_title: bool = False,
    cfg: dict | None = None,
    n: int | None = None,
    brief: str = "",
    on_progress=None,
) -> dict[str, Any]:
    """对批量内草稿条目按视频分组生成文案(候选取第 1 个填入, 全部候选落库)。

    brief: 批次统一 AI 提示词(整批共用, 约束风格/卖点)。为空时回退读取批次元数据。
    with_goods_title: 同时根据 brief(关键词/卖点)推断商品短标题——每视频 1 个,
      只填空(已有短标题的视频跳过), 写入视频及本批该视频全部条目的 goods_json。
    同一平台跨视频维护已用标题集合, 通过 prompt 排除 + 候选挑选保证标题差异化。
    on_progress(done, failed, total, current): 每个视频处理完回调一次(生成进度展示用)。
    """
    brief = (brief or "").strip() or store.get_batch_brief(batch_id)
    items = store.list_items(batch_id)
    by_video: dict[int, list[dict]] = {}
    for item in items:
        by_video.setdefault(item["video_id"], []).append(item)

    # 先算好本批实际要处理的视频组, 用于进度分母
    groups: list[tuple[int, list[dict], list[str]]] = []
    for video_id, group in by_video.items():
        group_platforms = [it["platform"] for it in group]
        if platforms:
            group_platforms = [p for p in group_platforms if p in platforms]
        if not group_platforms:
            continue
        groups.append((video_id, group, group_platforms))
    total = len(groups)

    used_titles: dict[str, set[str]] = {}
    used_goods_titles: set[str] = set()
    generated, failed = 0, 0
    goods_titles, goods_failed = 0, 0
    done = 0
    for video_id, group, group_platforms in groups:
        video = store.get_video(video_id)
        current = ""
        if video:
            current = str(video.get("base_title") or video.get("path") or "").split(chr(92))[-1][:30]
        base = {
            "title": (video.get("base_title") or "").strip(),
            "desc": video.get("base_desc", ""),
            "tags": video.get("base_tags", ""),
            "goods": _goods(video.get("goods_json")),
            "brief": brief,
        }
        if not base["title"] and not brief:
            for item in group:
                store.update_item(item["id"], status="needs_manual", error="缺少人工标题或批次 AI 提示词, 无法生成")
                failed += 1
            done += 1
            if on_progress:
                on_progress(done, failed, total, current)
            continue
        # prompt 层去重提示: 取所有平台已用标题的并集(跨平台近似即可, 选择层按平台精确去重)
        avoid = sorted({t for s in used_titles.values() for t in s})
        # 同平台多账号条目需要互不相同的标题: 按平台分组, 每平台请求 = 该平台条目数的候选
        per_platform_items: dict[str, list[dict]] = {}
        for it in group:
            per_platform_items.setdefault(it["platform"], []).append(it)
        need = max(len(v) for v in per_platform_items.values()) if per_platform_items else 1
        results = copy_engine.generate_copy(
            group_platforms, base, cfg=cfg, n=n or need, with_desc=with_desc, with_tags=with_tags,
            avoid_titles=avoid,
        )
        for platform, items_p in per_platform_items.items():
            if platform not in results:
                continue
            result = results[platform]
            if result.get("error"):
                for item in items_p:
                    store.update_item(
                        item["id"],
                        status="needs_manual",
                        error=f"文案生成失败: {result['error']}",
                        candidates_json="[]",
                    )
                    failed += 1
                continue
            cands = result.get("candidates") or []
            if not cands:
                for item in items_p:
                    store.update_item(
                        item["id"],
                        status="needs_manual",
                        error="文案生成失败: 无可用候选",
                        candidates_json="[]",
                    )
                    failed += 1
                continue
            used = used_titles.setdefault(platform, set())
            for idx, item in enumerate(items_p):
                # 组内第 idx 个账号优先取第 idx 个候选(多样化); 已被跨视频占用则向后找未用候选; 全部占用退回轮转
                pool = cands[idx:] + cands[:idx]
                chosen = next((c for c in pool if (c.get("title") or "").strip() and (c["title"].strip() not in used)), {})
                if not chosen.get("title"):
                    chosen = cands[idx % len(cands)]
                if chosen.get("title"):
                    used.add(chosen["title"].strip())
                store.update_item(
                    item["id"],
                    title=chosen.get("title", ""),
                    desc=chosen.get("desc", ""),
                    tags=",".join(chosen.get("tags") or []),
                    candidates_json=json.dumps(cands, ensure_ascii=False),
                    status="draft",
                    error="",
                )
                generated += 1
        # 商品短标题: 每视频 1 个, 只填空, 同步到本批该视频全部条目(保留 link/id)
        if with_goods_title and video and (base["title"] or brief):
            goods = _goods(video.get("goods_json"))
            if not str(goods.get("title") or "").strip():
                gt = copy_engine.generate_goods_title(base, cfg=cfg, avoid=sorted(used_goods_titles))
                if gt.get("title"):
                    used_goods_titles.add(gt["title"])
                    store.update_video(video_id, goods_json=json.dumps({**goods, "title": gt["title"]}, ensure_ascii=False))
                    for item in group:
                        merged = _goods(item.get("goods_json"))
                        merged["title"] = gt["title"]
                        store.update_item(item["id"], goods_json=json.dumps(merged, ensure_ascii=False))
                    goods_titles += 1
                else:
                    goods_failed += 1
        done += 1
        if on_progress:
            on_progress(done, failed, total, current)
    return {"batch_id": batch_id, "generated": generated, "failed": failed,
            "goods_titles": goods_titles, "goods_failed": goods_failed}


def approve_items(item_ids: list[int], approved: bool = True) -> int:
    status = "approved" if approved else "draft"
    count = 0
    for item_id in item_ids:
        item = store.get_item(item_id)
        if not item:
            continue
        if status == "approved" and item["status"] != "draft" and item["status"] != "needs_manual" and item["status"] != "skipped":
            continue  # skipped(防重发/定时过期/日上限)允许重新批准
        store.update_item(item_id, status=status)
        count += 1
    return count


def set_item_content(item_id: int, fields: dict[str, Any]) -> dict:
    """审阅时更新条目文案/状态。"""
    allowed = ["title", "desc", "tags", "schedule", "goods_json", "status", "account"]
    cleaned = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if "tags" in cleaned and isinstance(cleaned["tags"], list):
        cleaned["tags"] = ",".join(rules.clean_tags(cleaned["tags"]))
    store.update_item(item_id, **cleaned)
    return store.get_item(item_id) or {}


def update_item_goods(item_id: int, goods: dict) -> dict | None:
    """更新**单条目**的商品信息(只写该条目, 不扩散到同视频其他条目/账号)。

    为什么只写本条目: 商品ID是平台/账号级的(同一个视频发到抖音与天猫要用各自的
    商品ID), 早期实现把它同步到"同视频全部条目", 导致改 A 条会覆盖其他平台账号。
    视频级默认值(videos.goods_json)仅作为**新建条目时的播种值**, 由
    plan_batch/expand_items 读取; 需要改全批默认值时按视频改, 不要走这里。

    商品短标题(title)例外: 它由 generate_batch 按视频唯一生成并有意同步到
    同视频全部条目(保留各自的 link/id), 见本模块 generate_batch 的商品短标题段。
    """
    item = store.get_item(item_id)
    if not item:
        return None
    current = _goods(item.get("goods_json"))
    current.update({k: v for k, v in goods.items() if v is not None})
    store.update_item(item_id, goods_json=json.dumps(current, ensure_ascii=False))
    return store.get_item(item_id)


def retry_item(item_id: int) -> dict:
    item = store.get_item(item_id)
    if not item:
        raise RuntimeError(f"条目不存在: {item_id}")
    if item["status"] in ("success",):
        raise RuntimeError("已发布成功的条目不能重试")
    store.update_item(item_id, status="approved", error="", retry=item["retry"] + 1)
    return store.get_item(item_id) or {}


# ---------------------------------------------------------------------------
# 运行 / 停止 / 状态 / 报告
# ---------------------------------------------------------------------------
def run_batch(
    batch_id: str,
    *,
    interval_min: float = 5.0,
    daily_cap: int = 25,
    daily_caps: dict | None = None,
    max_concurrent: int = 4,
    dry_run: bool = False,
    draft: bool = False,
    headless: bool = False,
    force: bool = False,
    on_task_created=None,
) -> dict[str, Any]:
    pending = [it for it in store.list_items(batch_id) if it["status"] == "approved"]
    if not pending:
        return {"batch_id": batch_id, "error": "没有已批准的条目, 请先在审阅页批准"}
    scheduler.start_scheduler(
        batch_id,
        interval_min=interval_min,
        daily_cap=daily_cap,
        daily_caps=daily_caps,
        max_concurrent=max_concurrent,
        dry_run=dry_run,
        draft=draft,
        headless=headless,
        force=force,
        on_task_created=on_task_created,
    )
    return {"batch_id": batch_id, "started": len(pending)}


def stop_batch(batch_id: str) -> dict[str, Any]:
    stopped = scheduler.stop_scheduler(batch_id)
    return {"batch_id": batch_id, "stopped": stopped}


def batch_status(batch_id: str) -> dict[str, Any]:
    items = store.list_items(batch_id)
    videos = {v["id"]: v for v in store.list_videos()}
    summary = {"total": len(items), "draft": 0, "approved": 0, "running": 0,
               "success": 0, "failed": 0, "skipped": 0, "needs_manual": 0}
    for item in items:
        status = item["status"]
        if status in summary:
            summary[status] += 1
    sched = scheduler.scheduler_state(batch_id)
    return {
        "batch_id": batch_id,
        "summary": summary,
        "scheduler": sched,
        "items": [planner.public_item(it, videos.get(it["video_id"])) for it in items],
    }


def list_batches() -> list[dict]:
    """批次列表: items 聚合 + batches 元数据合并(未展开条目的批次也显示)。"""
    by_id: dict[str, dict] = {}
    for b in store.list_batches():
        by_id[b["batch_id"]] = b
    for m in store.list_batch_meta():
        b = by_id.setdefault(
            m["batch_id"],
            {"batch_id": m["batch_id"], "total": 0, "success": 0, "failed": 0, "running": 0, "created": m["created"]},
        )
        if not b.get("created"):
            b["created"] = m["created"]
    return sorted(by_id.values(), key=lambda x: x.get("created") or "", reverse=True)


def quota_info(batch_id: str, daily_caps: dict | None = None) -> dict[str, Any]:
    """运行前额度预览: 每个平台的已批准数 / 今日已发 / 上限 / 预计可发与将跳过数。"""
    caps = daily_caps or {}
    items = [it for it in store.list_items(batch_id) if it["status"] == "approved"]
    by_platform: dict[str, dict[str, Any]] = {}
    accounts: dict[str, set[str]] = {}
    for it in items:
        info = by_platform.setdefault(
            it["platform"],
            {"approved": 0, "published": 0, "cap": 0, "remaining": 0, "will_publish": 0, "will_skip": 0},
        )
        info["approved"] += 1
        accounts.setdefault(it["platform"], set()).add(it["account"])
    for platform, info in by_platform.items():
        cap = max(1, int(caps.get(platform) or 25))
        published = 0
        for account in accounts.get(platform, set()):
            published += store.published_count_today(account, platform)
        info["cap"] = cap
        info["published"] = published
        info["remaining"] = max(cap - published, 0)
        info["will_publish"] = min(info["approved"], info["remaining"])
        info["will_skip"] = info["approved"] - info["will_publish"]
    return {"batch_id": batch_id, "platforms": by_platform}


def report_csv(batch_id: str, out_path: str) -> str:
    items = store.list_items(batch_id)
    videos = {v["id"]: v for v in store.list_videos()}
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(BATCH_CSV_COLUMNS)
        for item in items:
            video = videos.get(item["video_id"], {})
            writer.writerow(
                [
                    rules.platform_cn(item["platform"]),
                    item["account"],
                    Path(video.get("path", "")).name,
                    item["title"],
                    item["desc"],
                    item["tags"],
                    item["schedule"],
                    item["status"],
                    item["error"],
                    item["published_at"],
                ]
            )
    return str(out)


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _goods(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except ValueError:
        return {}


def platform_candidates(item: dict) -> list[dict]:
    raw = item.get("candidates_json") or "[]"
    try:
        return json.loads(raw)
    except ValueError:
        return []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_batch_parser(subparsers) -> None:
    batch = subparsers.add_parser("batch", help="批量发布: 扫描/导入/生成/计划/运行/报告")
    actions = batch.add_subparsers(dest="action", required=True)

    scan = actions.add_parser("scan", help="扫描文件夹里的视频")
    scan.add_argument("--dir", required=True, help="视频文件夹")
    scan.add_argument("--batch-id", default=None, help="批次ID(默认自动生成)")
    scan.add_argument("--brief", default=None, help="批次统一 AI 提示词(整批共用)")

    imp = actions.add_parser("import", help="从 CSV 导入视频清单(每视频一行)")
    imp.add_argument("--csv", required=True, help="CSV 路径")
    imp.add_argument("--batch-id", default=None)
    imp.add_argument("--brief", default=None, help="批次统一 AI 提示词(整批共用)")

    fill = actions.add_parser("fill", help="给某视频填人工标题/描述等")
    fill.add_argument("--video-id", required=True, type=int)
    fill.add_argument("--title", default=None)
    fill.add_argument("--desc", default=None)
    fill.add_argument("--tags", default=None)
    fill.add_argument("--schedule", default=None)

    plan = actions.add_parser("plan", help="按视频×平台展开为条目")
    plan.add_argument("--batch-id", required=True)
    plan.add_argument("--video-id", action="append", type=int, default=None, help="指定视频(可多次), 默认全部")
    plan.add_argument("--platforms", default="douyin,kuaishou,tencent,xiaohongshu")
    plan.add_argument("--accounts", required=True, help="账号映射, 如 douyin:shop1,tencent:shop1")

    gen = actions.add_parser("generate", help="为条目生成各平台文案")
    gen.add_argument("--batch-id", required=True)
    gen.add_argument("--platforms", default=None)
    gen.add_argument("--brief", default=None, help="批次统一 AI 提示词(覆盖批次已存值)")
    gen.add_argument("--no-desc", action="store_true")
    gen.add_argument("--no-tags", action="store_true")
    gen.add_argument("--goods-title", action="store_true", help="同时生成商品短标题(只填空)")

    approve = actions.add_parser("approve", help="批准条目(进入可发布队列)")
    approve.add_argument("--batch-id", required=True)
    approve.add_argument("--item-id", action="append", type=int, default=None)

    run = actions.add_parser("run", help="运行批次(阻塞直到完成)")
    run.add_argument("--batch-id", required=True)
    run.add_argument("--interval-min", type=float, default=5.0)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--draft", action="store_true")
    run.add_argument("--force", action="store_true", help="忽略防重发检查")

    stop = actions.add_parser("stop", help="停止批次")
    stop.add_argument("--batch-id", required=True)

    status = actions.add_parser("status", help="查看批次状态")
    status.add_argument("--batch-id", required=True)

    retry = actions.add_parser("retry", help="重试失败条目")
    retry.add_argument("--item-id", required=True, type=int)

    report = actions.add_parser("report", help="导出批次报告 CSV")
    report.add_argument("--batch-id", required=True)
    report.add_argument("--csv", required=True)

    lst = actions.add_parser("list", help="列出批次")


def _print_items(items: list[dict]) -> None:
    print(f"{'ID':>5} {'平台':<8} {'状态':<12} 标题")
    for it in items:
        print(f"{it['id']:>5} {it['platform']:<8} {it['status']:<12} {it['title'][:40]}")


def dispatch_batch(args: argparse.Namespace) -> int:
    store.init_db()
    if args.action == "scan":
        result = scan_and_register(args.dir, args.batch_id)
        if getattr(args, "brief", None):
            store.set_batch_brief(result["batch_id"], args.brief)
        print(f"batch_id: {result['batch_id']}")
        for v in result["videos"]:
            print(f"  [{v['id']}] {v['path']} 标题='{v['base_title']}'")
        return 0
    if args.action == "import":
        result = import_and_register(args.csv, args.batch_id)
        if getattr(args, "brief", None):
            store.set_batch_brief(result["batch_id"], args.brief)
        print(f"batch_id: {result['batch_id']} 共 {len(result['videos'])} 个视频")
        return 0
    if args.action == "fill":
        renamed = {"title": "base_title", "desc": "base_desc", "tags": "base_tags", "schedule": "schedule"}
        mapped = {renamed[k]: v for k, v in vars(args).items() if k in renamed and v is not None}
        if not mapped:
            print("no fields to update")
            return 1
        update_video_fields(args.video_id, mapped)
        print("ok")
        return 0
    if args.action == "plan":
        videos = store.list_videos() if not args.video_id else [
            v for v in store.list_videos() if v["id"] in args.video_id
        ]
        platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]
        accounts = planner.parse_account_map(args.accounts)
        result = plan_batch(args.batch_id, [v["id"] for v in videos], platforms, accounts)
        print(f"created {result['created']} items")
        return 0
    if args.action == "generate":
        result = generate_batch(
            args.batch_id, _parse_platforms(args.platforms),
            with_desc=not args.no_desc, with_tags=not args.no_tags,
            with_goods_title=getattr(args, "goods_title", False),
            brief=getattr(args, "brief", None) or "",
        )
        print(f"generated {result['generated']}, failed {result['failed']}, goods_titles {result.get('goods_titles', 0)}")
        return 0
    if args.action == "approve":
        items = [it for it in store.list_items(args.batch_id)
                 if not args.item_id or it["id"] in args.item_id]
        n = approve_items([it["id"] for it in items])
        print(f"approved {n}")
        return 0
    if args.action == "run":
        result = run_batch(
            args.batch_id, interval_min=args.interval_min,
            dry_run=args.dry_run, draft=args.draft, force=args.force,
        )
        if result.get("error"):
            print(result["error"])
            return 1
        # CLI 阻塞直到调度结束
        while True:
            state = scheduler.scheduler_state(args.batch_id)
            if not state["alive"]:
                break
            time.sleep(5)
        return 0
    if args.action == "stop":
        stop_batch(args.batch_id)
        print("stop requested")
        return 0
    if args.action == "status":
        status = batch_status(args.batch_id)
        print(json.dumps(status["summary"], ensure_ascii=False))
        _print_items(status["items"])
        return 0
    if args.action == "retry":
        retry_item(args.item_id)
        print("ok")
        return 0
    if args.action == "report":
        path = report_csv(args.batch_id, args.csv)
        print(f"saved: {path}")
        return 0
    if args.action == "list":
        for b in list_batches():
            print(b)
        return 0
    raise RuntimeError(f"未知 batch 动作: {args.action}")


def _parse_platforms(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [p.strip() for p in raw.split(",") if p.strip()]
