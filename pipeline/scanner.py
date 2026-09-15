# -*- coding: utf-8 -*-
"""扫描器: 文件夹列视频(不读视频内容) + sidecar 解析 + CSV 导入导出。

CSV 格式(每视频一行, UTF-8 BOM):
  文件名, 人工标题, 描述, 标签, 定时发布时间, 封面路径, 商品链接, 商品短标题, 商品ID

sidecar: 与视频同目录同名 .md/.txt/.json, 可写 key: value 行或 JSON 对象,
  识别字段: 标题/描述/标签/商品链接/商品ID/定时发布时间/封面
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".flv", ".wmv", ".webm", ".avi"}

CSV_COLUMNS = [
    "文件名", "人工标题", "描述", "标签", "定时发布时间",
    "封面路径", "商品链接", "商品短标题", "商品ID",
]

_SIDECAR_KEYS = {
    "标题": "title", "人工标题": "title", "title": "title",
    "描述": "desc", "desc": "desc", "description": "desc",
    "标签": "tags", "tags": "tags", "tag": "tags",
    "商品链接": "product_link", "商品ID": "goods_id", "商品短标题": "product_title",
    "定时发布时间": "schedule", "封面": "cover", "cover": "cover",
}


def is_video_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTS


def video_meta(path: Path) -> dict[str, Any]:
    """单个视频的元数据(含 sidecar 解析), scan_dir 与"选择单条视频"登记共用。"""
    try:
        size = path.stat().st_size
        mtime = path.stat().st_mtime
    except OSError:
        size, mtime = 0, 0.0
    side = parse_sidecar(path)
    return {
        "path": str(path),
        "name": path.name,
        "size": size,
        "mtime": mtime,
        "base_title": side.get("title", ""),
        "base_desc": side.get("desc", ""),
        "base_tags": side.get("tags", ""),
        "goods_json": json.dumps(
            {
                "link": side.get("product_link", ""),
                "title": side.get("product_title", ""),
                "id": side.get("goods_id", ""),
            },
            ensure_ascii=False,
        ),
        "schedule": side.get("schedule", ""),
        "cover": side.get("cover", ""),
    }


def scan_dir(root: str | Path) -> list[dict[str, Any]]:
    """递归列出视频文件(不分析内容), 附带 sidecar 信息。"""
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(f"目录不存在: {root}")
    videos: list[dict[str, Any]] = []
    for p in sorted(root.rglob("*")):
        if not is_video_file(p):
            continue
        videos.append(video_meta(p))
    return videos


def sidecar_candidates(video_path: Path) -> list[Path]:
    return [video_path.with_suffix(ext) for ext in (".md", ".txt", ".json")]


def parse_sidecar(video_path: Path) -> dict[str, Any]:
    """解析同名 sidecar 文件; 不存在或不可读返回空 dict。"""
    for sc in sidecar_candidates(video_path):
        if not sc.is_file():
            continue
        try:
            text = sc.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        if sc.suffix == ".json":
            try:
                data = json.loads(text)
            except ValueError:
                continue
            if isinstance(data, dict):
                return {_SIDECAR_KEYS.get(k, k): v for k, v in data.items() if v}
            continue
        # .md/.txt: 每行 "key: value"
        out: dict[str, Any] = {}
        for line in text.splitlines():
            line = line.strip()
            if ":" not in line or line.startswith(("#", "//")):
                continue
            key, value = line.split(":", 1)
            key, value = key.strip(), value.strip()
            if not value:
                continue
            mapped = _SIDECAR_KEYS.get(key) or _SIDECAR_KEYS.get(key.lower())
            if mapped:
                out[mapped] = value
        return out
    return {}


def import_csv(path: str | Path) -> list[dict[str, Any]]:
    """导入"每视频一行"CSV, 返回与 scan_dir 相同结构的列表(只含存在的文件)。"""
    csv_path = Path(path)
    if not csv_path.is_file():
        raise FileNotFoundError(f"CSV 不存在: {csv_path}")
    rows: list[dict[str, Any]] = []
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("文件名") or "").strip()
            if not name:
                continue
            video = Path(name)
            if not video.is_absolute():
                video = csv_path.parent / video
            if not video.is_file():
                # 回退: 在 CSV 所在目录下递归按文件名找
                hits = [p for p in csv_path.parent.rglob(name) if p.is_file()]
                if hits:
                    video = hits[0]
            if not video.is_file() or not is_video_file(video):
                continue
            rows.append(
                {
                    "path": str(video),
                    "name": video.name,
                    "size": video.stat().st_size,
                    "mtime": video.stat().st_mtime,
                    "base_title": (row.get("人工标题") or "").strip(),
                    "base_desc": (row.get("描述") or "").strip(),
                    "base_tags": (row.get("标签") or "").strip(),
                    "goods_json": json.dumps(
                        {
                            "link": (row.get("商品链接") or "").strip(),
                            "title": (row.get("商品短标题") or "").strip(),
                            "id": (row.get("商品ID") or "").strip(),
                        },
                        ensure_ascii=False,
                    ),
                    "schedule": (row.get("定时发布时间") or "").strip(),
                    "cover": (row.get("封面路径") or "").strip(),
                }
            )
    return rows


def export_csv(rows: list[dict[str, Any]], out_path: str | Path) -> str:
    """导出视频清单(每视频一行), 返回文件路径。"""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)
        for r in rows:
            goods = r.get("goods_json") or "{}"
            if isinstance(goods, str):
                try:
                    goods = json.loads(goods)
                except ValueError:
                    goods = {}
            writer.writerow(
                [
                    Path(r["path"]).name,
                    r.get("base_title", ""),
                    r.get("base_desc", ""),
                    r.get("base_tags", ""),
                    r.get("schedule", ""),
                    r.get("cover", ""),
                    goods.get("link", ""),
                    goods.get("title", ""),
                    goods.get("id", ""),
                ]
            )
    return str(out)


def is_absolute_or_drive(path: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", path)) or path.startswith("\\\\")
