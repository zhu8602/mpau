# -*- coding: utf-8 -*-
"""批量调度器: 跨平台并发执行 + 风控节流。

- 不同「平台+账号」可同时上传(默认 max_concurrent 个并发); 同一「平台+账号」保持串行
- 条间间隔 interval_min 按「平台+账号」计(同账号连续两条之间 >= interval_min 分钟)
- 按平台每日发布上限(platform_daily_caps, 未配置用 daily_cap 兜底), 达限条目标记跳过并写明原因
- 每条执行前检查 published 表防重发; 定时时间已过(>2h)的条目标记跳过
- 执行中可 stop(结束所有正在运行的子进程, 后续条目不再启动)
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any

from pipeline import planner, rules, runner, store

SCHEDULE_FORMAT = "%Y-%m-%d %H:%M"

# 运行中的调度器注册表: batch_id -> BatchScheduler
_running: dict[str, "BatchScheduler"] = {}
_registry_lock = threading.Lock()


class BatchScheduler(threading.Thread):
    def __init__(
        self,
        batch_id: str,
        *,
        interval_min: float = 5.0,
        daily_cap: int = 25,
        daily_caps: dict | None = None,
        max_concurrent: int = 3,
        dry_run: bool = False,
        draft: bool = False,
        headless: bool = False,
        force: bool = False,
        on_task_created=None,
    ):
        super().__init__(daemon=True, name=f"batch-{batch_id}")
        self.batch_id = batch_id
        # 仅保留 1 秒安全下限; 生产策略(1-60 分钟)由 /api/batch/run 与配置层钳制
        self.interval_sec = max(float(interval_min), 1 / 60) * 60
        self.daily_cap = daily_cap
        self.daily_caps = dict(daily_caps or {})  # 平台 -> 每日上限(未配置用 daily_cap 兜底)
        self.max_concurrent = max(1, int(max_concurrent))
        self.dry_run = dry_run
        self.draft = draft
        self.headless = headless
        self.force = force
        self.on_task_created = on_task_created
        # 注意: 成员不能叫 _stop(会覆盖 threading.Thread 的内部方法 _stop())
        self._stop_event = threading.Event()
        self._procs: list = []  # 所有运行中的子进程(并发多进程)
        self._in_flight: dict[tuple, threading.Thread] = {}  # (platform, account) -> 工作线程
        self._last_launch: dict[tuple, float] = {}  # (platform, account) -> 上次启动时间
        self._lock = threading.Lock()
        self.message = ""  # 当前状态描述(供 status 接口)

    # ------------------------------------------------------------------
    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            procs = list(self._procs)
        for proc in procs:
            if proc.poll() is None:
                runner.kill_by_pid(proc.pid)

    def _log(self, text: str) -> None:
        self.message = text

    def _reap(self) -> None:
        """清理已结束的工作线程。"""
        with self._lock:
            for key in [k for k, t in self._in_flight.items() if not t.is_alive()]:
                self._in_flight.pop(key, None)

    # ------------------------------------------------------------------
    def run(self) -> None:
        while not self._stop_event.is_set():
            self._reap()
            item = self._next_eligible()
            if item is None:
                with self._lock:
                    busy = len(self._in_flight)
                if busy:
                    self._log(f"没有新的可发布条目, 等待 {busy} 个上传完成...")
                    self._stop_event.wait(1)
                    continue
                self._log("没有可发布的条目, 调度结束")
                break

            key = (item["platform"], item["account"])
            # 节流: 同一「平台+账号」两条之间最小间隔
            wait = self._last_launch.get(key, 0) + self.interval_sec - time.time()
            if wait > 0:
                self._log(f"{rules.platform_cn(item['platform'])} 节流等待 {int(wait)}s...")
                self._stop_event.wait(wait)
                if self._stop_event.is_set():
                    break

            # 平台日上限: 达到则跳过该条并写明原因, 不空等(用户可明天重试或调高上限)
            if not self._check_daily_cap(item):
                cap = self._cap_for(item["platform"])
                store.update_item(
                    item["id"], status="skipped",
                    error=f"今日 {rules.platform_cn(item['platform'])} 已发布 {cap} 条, 达到日上限, 请明天再试或调高上限",
                )
                self._log(f"{rules.platform_cn(item['platform'])} 今日已达上限 {cap} 条, 跳过该条")
                continue

            # 并发上限: 在飞上传数达到 max_concurrent 时等待空位
            with self._lock:
                busy = len(self._in_flight)
            if busy >= self.max_concurrent:
                self._log(f"并发已满({busy}/{self.max_concurrent}), 等待空位...")
                self._stop_event.wait(1)
                continue

            self._last_launch[key] = time.time()
            worker = threading.Thread(
                target=self._launch, args=(item, key), daemon=True,
                name=f"batch-{self.batch_id}-{item['id']}",
            )
            with self._lock:
                self._in_flight[key] = worker
            worker.start()
        self._log("调度结束")

    # ------------------------------------------------------------------
    def _next_eligible(self) -> dict | None:
        """取一条 approved 且满足定时/防重/未占用(同平台同账号不在飞)的条目。"""
        with self._lock:
            busy_keys = set(self._in_flight.keys())
        for item in store.list_items(self.batch_id):
            if item["status"] != "approved":
                continue
            if (item["platform"], item["account"]) in busy_keys:
                continue  # 同「平台+账号」已在飞, 等它完成(保风控)
            video = store.get_video(item["video_id"])
            if not video:
                store.update_item(item["id"], status="failed", error="视频记录丢失")
                continue
            # 防重发
            if (
                not self.force
                and video.get("sha256")
                and store.is_published(video["sha256"], item["platform"], item["account"])
            ):
                store.update_item(item["id"], status="skipped", error="该视频已在对应平台账号发布过(防重发)")
                continue
            # 定时检查
            err = check_schedule(item.get("schedule") or "")
            if err:
                store.update_item(item["id"], status="skipped", error=err)
                continue
            if item.get("schedule") and _schedule_in_future(item["schedule"]):
                continue  # 还没到点, 继续等
            return item
        return None

    def _cap_for(self, platform: str) -> int:
        try:
            return max(1, int(self.daily_caps.get(platform) or self.daily_cap))
        except (TypeError, ValueError):
            return max(1, int(self.daily_cap))

    def _check_daily_cap(self, item: dict) -> bool:
        account = item["account"]
        platform = item["platform"]
        done_today = store.published_count_today(account, platform)
        for it in store.list_items(self.batch_id):
            if it["account"] == account and it["platform"] == platform and it["status"] in ("running", "queued"):
                done_today += 1
        return done_today < self._cap_for(platform)

    # ------------------------------------------------------------------
    def _launch(self, item: dict, key: tuple) -> None:
        try:
            self._launch_inner(item)
        finally:
            with self._lock:
                self._in_flight.pop(key, None)

    def _launch_inner(self, item: dict) -> None:
        video = store.get_video(item["video_id"])
        if not video:
            store.update_item(item["id"], status="failed", error="视频记录丢失")
            return
        try:
            cmd = planner.build_upload_cmd(
                item["platform"],
                item["account"],
                video["path"],
                title=item["title"],
                desc=item["desc"],
                tags=[t for t in (item["tags"] or "").split(",") if t],
                schedule=item.get("schedule") or "",
                product_link=_goods(item).get("link", ""),
                product_title=_goods(item).get("title", ""),
                goods_id=_goods(item).get("id", ""),
                goods_name=_goods(item).get("name", ""),
                draft=self.draft,
                dry_run=self.dry_run,
                headless=self.headless,
            )
        except ValueError as exc:
            store.update_item(item["id"], status="failed", error=str(exc))
            return

        task_id = f"b{item['id']}-r{item['retry']}"
        task = {
            "id": task_id,
            "kind": "batch-upload",
            "platform": item["platform"],
            "account": item["account"],
            "label": f"批量发布 {rules.platform_cn(item['platform'])} {video['path'].split(chr(92))[-1]}",
            "cmd": " ".join(cmd),
            "cmd_display": " ".join(cmd),
            "status": "running",
            "error": "",
            "exit": None,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "started": time.strftime("%Y-%m-%d %H:%M:%S"),
            "finished": "",
            "log": "",
        }
        store.save_task(task)
        store.update_item(item["id"], status="running", task_id=task_id, error="")
        if self.on_task_created:
            try:
                self.on_task_created(task)
            except Exception:  # noqa: BLE001
                pass

        tail: list[str] = []

        def on_line(line: str) -> None:
            store.append_task_log(task_id, line)
            tail.append(line)
            if len(tail) > 40:
                del tail[:-40]

        try:
            proc = runner.spawn_mpau(cmd)
        except RuntimeError as exc:
            store.update_item(item["id"], status="failed", error=str(exc))
            store.update_task(task_id, status="failed", error=str(exc), finished=_now())
            return
        with self._lock:
            self._procs.append(proc)
        exit_code = runner.stream_mpau(proc, on_line)
        with self._lock:
            if proc in self._procs:
                self._procs.remove(proc)
        if self._stop_event.is_set():
            store.update_item(item["id"], status="approved", error="调度被停止, 条目回到待发")
            store.update_task(task_id, status="canceled", exit=exit_code, finished=_now())
            return
        if exit_code == 0:
            store.update_item(
                item["id"], status="success", error="",
                published_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            )
            store.mark_published(
                video.get("sha256") or _fallback_hash(video["path"]),
                item["platform"], item["account"],
            )
            store.update_task(task_id, status="success", exit=0, finished=_now())
        else:
            err_tail = "\n".join(tail[-12:])[-500:]
            store.update_item(item["id"], status="failed", error=err_tail or f"退出码 {exit_code}")
            store.update_task(task_id, status="failed", exit=exit_code, error=err_tail, finished=_now())


def _fallback_hash(path: str) -> str:
    h = store.sha256_file(path)
    return h or f"path:{path}"


def _goods(item: dict) -> dict:
    import json

    raw = item.get("goods_json") or "{}"
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except ValueError:
        return {}


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _schedule_in_future(schedule: str) -> bool:
    try:
        return datetime.strptime(schedule, SCHEDULE_FORMAT) > datetime.now()
    except ValueError:
        return False


def check_schedule(schedule: str) -> str:
    """返回错误信息; 空串表示 OK。"""
    schedule = (schedule or "").strip()
    if not schedule:
        return ""
    try:
        due = datetime.strptime(schedule, SCHEDULE_FORMAT)
    except ValueError:
        return f"定时时间格式错误: {schedule}(应为 YYYY-MM-DD HH:MM)"
    delta_h = (datetime.now() - due).total_seconds() / 3600
    if delta_h > 2:
        return f"定时时间已过(超2小时): {schedule}"
    return ""


def start_scheduler(
    batch_id: str,
    *,
    interval_min: float = 5.0,
    daily_cap: int = 25,
    daily_caps: dict | None = None,
    max_concurrent: int = 3,
    dry_run: bool = False,
    draft: bool = False,
    headless: bool = False,
    force: bool = False,
    on_task_created=None,
) -> BatchScheduler:
    with _registry_lock:
        old = _running.pop(batch_id, None)
    if old and old.is_alive():
        old.stop()
    sched = BatchScheduler(
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
    with _registry_lock:
        _running[batch_id] = sched
    sched.start()
    return sched


def stop_scheduler(batch_id: str) -> bool:
    with _registry_lock:
        sched = _running.pop(batch_id, None)
    if sched:
        sched.stop()
        return True
    return False


def scheduler_state(batch_id: str) -> dict[str, Any]:
    with _registry_lock:
        sched = _running.get(batch_id)
    if not sched:
        return {"running": False, "alive": False, "message": ""}
    return {"running": True, "alive": sched.is_alive(), "message": sched.message}
