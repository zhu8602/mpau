# -*- coding: utf-8 -*-
"""查询任务历史与发布记录(诊断用)。"""
import sqlite3

from pipeline import store

store.init_db()
print("=== 任务列表 ===")
for t in store.load_tasks():
    log_tail = (t.get("log") or [])
    print(f"{t['id']} | {t['kind']} | {t['platform']} | {t['account']} | {t['status']} | {t['created']} | {t['label']}")
    if t["error"]:
        print(f"    error: {t['error'][:200]}")
    print(f"    cmd: {t.get('cmd','')[:160]}")

print()
print("=== published 表(防重发记录) ===")
c = sqlite3.connect("data/mpau.db")
for r in c.execute("SELECT sha256, platform, account, published_at FROM published ORDER BY published_at DESC"):
    print(r)

print()
print("=== 今日统计 ===")
try:
    print(store.today_stats())
except Exception as e:  # noqa: BLE001
    print("today_stats 失败:", e)
