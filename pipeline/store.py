# -*- coding: utf-8 -*-
"""SQLite 持久层: 任务 / 批量视频 / 批量条目 / 防重发 / 设置。

数据库文件: MPAU_HOME/data/mpau.db(默认; 可用 MPAU_DATA_DIR 覆盖, 已被 .gitignore 排除, 不进打包 zip)。
所有写操作持锁, 每个操作独立连接, 适合 Flask 多线程与 CLI 混用。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from utils.config import MPAU_HOME

# 测试可注入 MPAU_DATA_DIR 隔离数据库
DATA_DIR = Path(os.getenv("MPAU_DATA_DIR", str(MPAU_HOME / "data")))
DB_PATH = DATA_DIR / "mpau.db"

_write_lock = threading.RLock()  # RLock: 允许回调嵌套写

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT '',
  platform TEXT NOT NULL DEFAULT '',
  account TEXT NOT NULL DEFAULT '',
  label TEXT NOT NULL DEFAULT '',
  cmd TEXT NOT NULL DEFAULT '',
  cmd_display TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'queued',
  error TEXT NOT NULL DEFAULT '',
  exit INTEGER,
  created TEXT NOT NULL DEFAULT '',
  started TEXT NOT NULL DEFAULT '',
  finished TEXT NOT NULL DEFAULT '',
  log TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS videos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  path TEXT UNIQUE NOT NULL,
  sha256 TEXT NOT NULL DEFAULT '',
  size INTEGER NOT NULL DEFAULT 0,
  base_title TEXT NOT NULL DEFAULT '',
  base_desc TEXT NOT NULL DEFAULT '',
  base_tags TEXT NOT NULL DEFAULT '',
  goods_json TEXT NOT NULL DEFAULT '{}',
  schedule TEXT NOT NULL DEFAULT '',
  cover TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'new'
);
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id TEXT NOT NULL DEFAULT '',
  video_id INTEGER NOT NULL,
  platform TEXT NOT NULL,
  account TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  desc TEXT NOT NULL DEFAULT '',
  tags TEXT NOT NULL DEFAULT '',
  candidates_json TEXT NOT NULL DEFAULT '[]',
  schedule TEXT NOT NULL DEFAULT '',
  goods_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'draft',
  task_id TEXT NOT NULL DEFAULT '',
  retry INTEGER NOT NULL DEFAULT 0,
  error TEXT NOT NULL DEFAULT '',
  created TEXT NOT NULL DEFAULT '',
  updated TEXT NOT NULL DEFAULT '',
  published_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS batches (
  batch_id TEXT PRIMARY KEY,
  brief TEXT NOT NULL DEFAULT '',
  video_ids TEXT NOT NULL DEFAULT '',
  created TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS published (
  sha256 TEXT NOT NULL,
  platform TEXT NOT NULL,
  account TEXT NOT NULL,
  published_at TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (sha256, platform, account)
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_items_batch ON items(batch_id);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created);
"""


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """老库字段补齐(ALTER TABLE 幂等迁移)。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(batches)").fetchall()}
    if "video_ids" not in cols:
        conn.execute("ALTER TABLE batches ADD COLUMN video_ids TEXT NOT NULL DEFAULT ''")
    item_cols = {r["name"] for r in conn.execute("PRAGMA table_info(items)").fetchall()}
    if "updated" not in item_cols:
        conn.execute("ALTER TABLE items ADD COLUMN updated TEXT NOT NULL DEFAULT ''")
        conn.execute("UPDATE items SET updated = created WHERE updated = ''")


def sha256_file(path: str | Path) -> str:
    """分块计算文件 sha256(大视频安全)。文件不存在返回空串。"""
    p = Path(path)
    if not p.is_file():
        return ""
    h = hashlib.sha256()
    try:
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


# ---------------------------------------------------------------------------
# 任务表(与 web/app.py 的内存队列同构, 落库持久化)
# ---------------------------------------------------------------------------
def save_task(task: dict) -> None:
    cmd = task.get("cmd", "")
    if isinstance(cmd, (list, tuple)):
        cmd = " ".join(str(c) for c in cmd)
    cmd_display = task.get("cmd_display", "") or cmd
    log = task.get("log", "")
    if isinstance(log, list):
        log = "\n".join(str(x) for x in log)
    with _write_lock, _conn() as conn:
        conn.execute(
            """INSERT INTO tasks(id, kind, platform, account, label, cmd, cmd_display,
                                 status, error, exit, created, started, finished, log)
               VALUES(:id, :kind, :platform, :account, :label, :cmd, :cmd_display,
                      :status, :error, :exit, :created, :started, :finished, :log)
               ON CONFLICT(id) DO UPDATE SET
                 kind=excluded.kind, platform=excluded.platform, account=excluded.account,
                 label=excluded.label, cmd=excluded.cmd, cmd_display=excluded.cmd_display,
                 status=excluded.status, error=excluded.error, exit=excluded.exit,
                 created=excluded.created, started=excluded.started,
                 finished=excluded.finished, log=excluded.log""",
            {
                "id": task.get("id", ""),
                "kind": task.get("kind", ""),
                "platform": task.get("platform", ""),
                "account": task.get("account", ""),
                "label": task.get("label", ""),
                "cmd": cmd,
                "cmd_display": cmd_display,
                "status": task.get("status", "queued"),
                "error": task.get("error", ""),
                "exit": task.get("exit"),
                "created": task.get("created", ""),
                "started": task.get("started", ""),
                "finished": task.get("finished", ""),
                "log": log,
            },
        )


def update_task(task_id: str, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    with _write_lock, _conn() as conn:
        conn.execute(f"UPDATE tasks SET {cols} WHERE id = ?", (*fields.values(), task_id))


def append_task_log(task_id: str, line: str) -> None:
    with _write_lock, _conn() as conn:
        conn.execute("UPDATE tasks SET log = log || ? WHERE id = ?", (line + "\n", task_id))


def load_tasks() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY created DESC, id DESC").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["log"] = d["log"].splitlines()
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# 批量视频(videos 表)
# ---------------------------------------------------------------------------
def upsert_video(path: str, **fields: Any) -> int:
    with _write_lock, _conn() as conn:
        conn.execute(
            """INSERT INTO videos(path) VALUES(?) ON CONFLICT(path) DO NOTHING""",
            (str(path),),
        )
        row = conn.execute("SELECT id FROM videos WHERE path = ?", (str(path),)).fetchone()
        video_id = row["id"]
        if fields:
            cols = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(f"UPDATE videos SET {cols} WHERE id = ?", (*fields.values(), video_id))
    return video_id


def update_video(video_id: int, **fields: Any) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    with _write_lock, _conn() as conn:
        conn.execute(f"UPDATE videos SET {cols} WHERE id = ?", (*fields.values(), video_id))


def get_video(video_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
    return dict(row) if row else None


def get_video_by_path(path: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM videos WHERE path = ?", (str(path),)).fetchone()
    return dict(row) if row else None


def list_videos() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM videos ORDER BY path").fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 批量条目(items 表)
# ---------------------------------------------------------------------------
def create_item(**fields: Any) -> int:
    fields.setdefault("created", _now())
    fields.setdefault("updated", fields["created"])
    cols = ", ".join(fields.keys())
    marks = ", ".join("?" for _ in fields)
    with _write_lock, _conn() as conn:
        cur = conn.execute(f"INSERT INTO items({cols}) VALUES({marks})", tuple(fields.values()))
        return int(cur.lastrowid)


def update_item(item_id: int, **fields: Any) -> None:
    if not fields:
        return
    fields.setdefault("updated", _now())
    cols = ", ".join(f"{k} = ?" for k in fields)
    with _write_lock, _conn() as conn:
        conn.execute(f"UPDATE items SET {cols} WHERE id = ?", (*fields.values(), item_id))


def get_item(item_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    return dict(row) if row else None


def item_exists(batch_id: str, video_id: int, platform: str, account: str = "") -> dict | None:
    """该批次里 (视频, 平台[, 账号]) 是否已有条目; 有则返回条目。

    多账号模式下同一 视频×平台 会按账号生成多条, 传入 account 精确匹配;
    不传 account 时保持旧语义(任一账号的条目)。
    """
    with _conn() as conn:
        if account:
            row = conn.execute(
                "SELECT * FROM items WHERE batch_id=? AND video_id=? AND platform=? AND account=?",
                (batch_id, video_id, platform, account),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM items WHERE batch_id=? AND video_id=? AND platform=?",
                (batch_id, video_id, platform),
            ).fetchone()
    return dict(row) if row else None


def list_items(batch_id: str | None = None) -> list[dict]:
    with _conn() as conn:
        if batch_id:
            rows = conn.execute(
                "SELECT * FROM items WHERE batch_id = ? ORDER BY id", (batch_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM items ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def list_batches() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """SELECT batch_id,
                      COUNT(*) AS total,
                      SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS success,
                      SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                      SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) AS running,
                      MIN(created) AS created
               FROM items GROUP BY batch_id ORDER BY created DESC"""
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 批次元数据(batches 表): 统一 AI 提示词等
# ---------------------------------------------------------------------------
def set_batch_brief(batch_id: str, brief: str) -> None:
    """保存批次统一 AI 提示词(整批共用, LLM 生成输入)。空串也允许(清空)。"""
    batch_id = (batch_id or "").strip()
    if not batch_id:
        return
    with _write_lock, _conn() as conn:
        conn.execute(
            """INSERT INTO batches(batch_id, brief, created) VALUES(?, ?, ?)
               ON CONFLICT(batch_id) DO UPDATE SET brief=excluded.brief""",
            (batch_id, (brief or "").strip(), _now()),
        )


def get_batch_brief(batch_id: str) -> str:
    if not batch_id:
        return ""
    with _conn() as conn:
        row = conn.execute(
            "SELECT brief FROM batches WHERE batch_id = ?", (batch_id,)
        ).fetchone()
    return str(row["brief"]) if row else ""


def set_batch_videos(batch_id: str, video_ids: list[int]) -> None:
    """登记该批次扫描/导入注册的视频清单(批次内视频隔离的依据)。"""
    batch_id = (batch_id or "").strip()
    if not batch_id:
        return
    with _write_lock, _conn() as conn:
        conn.execute(
            """INSERT INTO batches(batch_id, video_ids, created) VALUES(?, ?, ?)
               ON CONFLICT(batch_id) DO UPDATE SET video_ids=excluded.video_ids""",
            (batch_id, json.dumps([int(v) for v in video_ids], ensure_ascii=False), _now()),
        )


def get_batch_videos(batch_id: str) -> list[int]:
    """该批次已登记的视频 id 清单(未登记返回空列表)。"""
    if not batch_id:
        return []
    with _conn() as conn:
        row = conn.execute(
            "SELECT video_ids FROM batches WHERE batch_id = ?", (batch_id,)
        ).fetchone()
    if not row:
        return []
    try:
        return [int(v) for v in json.loads(row["video_ids"] or "[]")]
    except (ValueError, TypeError):
        return []


def delete_batch(batch_id: str) -> None:
    """删除批次及其条目(视频记录保留, 避免影响其他批次引用)。"""
    if not batch_id:
        return
    with _write_lock, _conn() as conn:
        conn.execute("DELETE FROM items WHERE batch_id = ?", (batch_id,))
        conn.execute("DELETE FROM batches WHERE batch_id = ?", (batch_id,))


def list_batch_meta() -> list[dict]:
    """batches 表元数据(含未展开条目的批次)。"""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT batch_id, created FROM batches ORDER BY created DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 防重发(published 表)
# ---------------------------------------------------------------------------
def is_published(sha256: str, platform: str, account: str) -> bool:
    if not sha256:
        return False
    with _conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM published WHERE sha256=? AND platform=? AND account=?",
            (sha256, platform, account),
        ).fetchone()
    return row is not None


def published_at(sha256: str, platform: str, account: str) -> str:
    """某视频在某平台账号的发布时间(未发布返回空串)。"""
    if not sha256:
        return ""
    with _conn() as conn:
        row = conn.execute(
            "SELECT published_at FROM published WHERE sha256=? AND platform=? AND account=?",
            (sha256, platform, account),
        ).fetchone()
    return str(row["published_at"]) if row else ""


def mark_published(sha256: str, platform: str, account: str) -> None:
    if not sha256:
        return
    with _write_lock, _conn() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO published(sha256, platform, account, published_at)
               VALUES(?, ?, ?, ?)""",
            (sha256, platform, account, _now()),
        )


def published_count_today(account: str, platform: str = "") -> int:
    """某账号(可按平台过滤)今天已发布条数(用于日上限风控)。"""
    today = time.strftime("%Y-%m-%d")
    with _conn() as conn:
        if platform:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM published WHERE account=? AND platform=? AND published_at LIKE ?",
                (account, platform, today + "%"),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM published WHERE account=? AND published_at LIKE ?",
                (account, today + "%"),
            ).fetchone()
    return int(row["n"]) if row else 0


def today_stats() -> dict:
    """今日数据看板: 今日发布/较昨日/成功/成功率/排队/待处理。"""
    today = time.strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    with _conn() as conn:
        pub_today = conn.execute(
            "SELECT COUNT(*) FROM published WHERE published_at LIKE ?", (today + "%",)
        ).fetchone()[0]
        pub_yesterday = conn.execute(
            "SELECT COUNT(*) FROM published WHERE published_at LIKE ?", (yesterday + "%",)
        ).fetchone()[0]
        ok = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status='success' AND finished LIKE ?",
            (today + "%",),
        ).fetchone()[0]
        bad = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status='failed' AND finished LIKE ?",
            (today + "%",),
        ).fetchone()[0]
        queued = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE status IN ('queued','running')"
        ).fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM items WHERE status='approved'"
        ).fetchone()[0]
    rate = round(ok / (ok + bad) * 100) if (ok + bad) else 0
    return {
        "published": int(pub_today),
        "vs_yesterday": int(pub_today) - int(pub_yesterday),
        "success": int(ok),
        "success_rate": rate,
        "queued": int(queued),
        "pending": int(pending),
    }


# ---------------------------------------------------------------------------
# 设置(settings 表)
# ---------------------------------------------------------------------------
def get_setting(key: str, default: Any = None) -> Any:
    with _conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value"])
    except (ValueError, TypeError):
        return row["value"]


def set_setting(key: str, value: Any) -> None:
    with _write_lock, _conn() as conn:
        conn.execute(
            """INSERT INTO settings(key, value) VALUES(?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, json.dumps(value, ensure_ascii=False)),
        )
