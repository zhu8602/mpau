# -*- coding: utf-8 -*-
"""
mpau Web 管理后台
=================
在 multi-platform-auto-upload 之上包一层 Web UI:
  - 账号管理(扫码登录 / 状态检查 / 二维码展示)
  - 上传任务队列(视频/图文/定时/挂商品, 后台执行, 日志实时查看)
  - 短信验证码提交(抖音二次验证)

启动:
  uv run python web/app.py          # 默认 http://127.0.0.1:8898
环境变量:
  MPAU_WEB_PORT       端口, 默认 8898
  MPAU_WEB_HOST       绑定地址, 默认 127.0.0.1(设 0.0.0.0 为局域网模式)
  MPAU_WEB_TOKEN      访问令牌, 默认自动生成并写入 <data>/web_token.txt
  MPAU_WEB_FILES_ROOT 文件浏览默认目录, 默认 D:\\videos
"""
from __future__ import annotations

import itertools
import json
import os
import re
import secrets
import shutil
import subprocess
import threading
import time
from pathlib import Path

# 安装版以 `python app/web/app.py` 方式启动时 sys.path 不含项目根, 这里补上(dev 模式无害)
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask, jsonify, redirect, render_template, request, send_from_directory

from pipeline import account_meta, batch_runner, copy_engine, planner, rules, runner, store
from pipeline.config import load_config, mask_key, save_config
from pipeline.planner import PLATFORMS, PLATFORM_OPTS
from pipeline.rules import CORE_PLATFORMS
from utils import ui_window
from utils.config import COOKIES_DIR

BASE_DIR = Path(__file__).resolve().parents[1]
PACKAGE_DIR = BASE_DIR / "package"
DEFAULT_FILES_ROOT = Path(os.getenv("MPAU_WEB_FILES_ROOT", "D:\\videos"))

PLATFORM_CN = {
    "douyin": "抖音", "kuaishou": "快手", "xiaohongshu": "小红书",
    "tencent": "视频号", "pdd": "PDD多多视频", "tmall": "天猫/淘宝光合",
    "jd": "京东京麦", "baijiahao": "百家号", "tiktok": "TikTok",
}
NOTE_PLATFORMS = {"douyin", "kuaishou", "xiaohongshu"}
VERIFY_PLATFORMS = {"douyin"}
CHECK_SUPPORTED = {"douyin", "kuaishou", "xiaohongshu", "tencent", "pdd", "tmall", "jd", "baijiahao", "tiktok"}
# 终态任务状态: 判据见 api_tasks()——内存副本仅在自己处于终态或 DB 未终态时才权威
TERMINAL_TASK_STATUSES = {"success", "failed", "canceled"}

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

# ---------------------------------------------------------------------------
# 访问控制: 令牌认证(默认仅本机; 局域网模式也必须持令牌访问)
# ---------------------------------------------------------------------------
DATA_DIR = store.DATA_DIR  # 与 SQLite 同目录(测试经 MPAU_DATA_DIR 隔离)
TOKEN_FILE = DATA_DIR / "web_token.txt"
AUTH_COOKIE = "mpau_token"
_AUTH_TOKEN: str | None = None


def web_token() -> str:
    """访问令牌: MPAU_WEB_TOKEN 环境变量 > data/web_token.txt(不存在则自动生成)。"""
    global _AUTH_TOKEN
    if _AUTH_TOKEN:
        return _AUTH_TOKEN
    env = (os.getenv("MPAU_WEB_TOKEN") or "").strip()
    if env:
        _AUTH_TOKEN = env
        return _AUTH_TOKEN
    if TOKEN_FILE.is_file():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            _AUTH_TOKEN = token
            return _AUTH_TOKEN
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(24)
    TOKEN_FILE.write_text(token, encoding="utf-8")
    _AUTH_TOKEN = token
    return token


def _token_ok(token: str) -> bool:
    return bool(token) and secrets.compare_digest(token, web_token())


def _provided_token() -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return (request.headers.get("X-MPAU-Token") or "").strip() or request.cookies.get(AUTH_COOKIE, "")


def _set_auth_cookie(resp):
    resp.set_cookie(AUTH_COOKIE, web_token(), httponly=True, samesite="Lax", max_age=30 * 24 * 3600)
    return resp


@app.before_request
def require_auth():
    """除 /login 与 /manual 外全部需要令牌; Cookie 认证的写操作要求同源(防 CSRF)。"""
    if request.path in ("/login", "/manual"):
        return None
    # 浏览器入口: http://<host>:<port>/?token=XXX 种下 Cookie 后跳转
    if request.path == "/" and request.method == "GET":
        query_token = (request.args.get("token") or "").strip()
        if query_token and _token_ok(query_token):
            return _set_auth_cookie(redirect("/"))
    if _token_ok(_provided_token()):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            fetch_site = (request.headers.get("Sec-Fetch-Site") or "").lower()
            if fetch_site and fetch_site not in ("same-origin", "same-site", "none"):
                return jsonify({"error": "cross-site request blocked"}), 403
        return None
    if request.path.startswith("/api/") or request.method != "GET":
        return jsonify({"error": "unauthorized, 请携带访问令牌(?token= 入口或 X-MPAU-Token 头)"}), 401
    return redirect("/login")


@app.route("/login", methods=["GET", "POST"])
def login_page():
    if request.method == "POST":
        if _token_ok((request.form.get("token") or "").strip()):
            return _set_auth_cookie(redirect("/"))
        return render_template("login.html", error="令牌不正确"), 403
    if _token_ok(_provided_token()):
        return redirect("/")
    return render_template("login.html", error="")


# ---------------------------------------------------------------------------
# UI 窗口(安装版): 由启动器/托盘触发, 以内置 Chromium --app 模式打开主界面
# ---------------------------------------------------------------------------
_WEB_PORT = int(os.getenv("MPAU_WEB_PORT", "8898"))
_ui_procs: list[subprocess.Popen] = []


def open_ui_window() -> str:
    """打开主界面并跟踪窗口句柄; 返回打开方式(chromium-app / default-browser)。"""
    mode, proc = ui_window.open_main_window(f"http://127.0.0.1:{_WEB_PORT}/?token={web_token()}")
    if proc is not None:
        _ui_procs.append(proc)
    return mode


def shutdown_server() -> None:
    """托盘「退出」入口: 关掉 UI 窗口后结束后台服务(进行中的任务随之中断)。"""
    for p in _ui_procs:
        try:
            p.terminate()
        except OSError:
            pass
    os._exit(0)


@app.post("/api/open-ui")
def api_open_ui():
    return jsonify({"ok": True, "mode": open_ui_window()})

# ---------------------------------------------------------------------------
# 任务队列(内存态 + SQLite 持久化; RLock 允许回调内嵌套加锁)
# ---------------------------------------------------------------------------
_tasks: dict[str, dict] = {}
_tasks_lock = threading.RLock()
_seq = itertools.count(1)
MAX_LOG_LINES = 600


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def append_log(task: dict, line: str):
    with _tasks_lock:
        task["log"].append(f"[{_now()}] {line}")
        if len(task["log"]) > MAX_LOG_LINES:
            task["log"] = task["log"][-MAX_LOG_LINES:]


def run_task(task: dict):
    """在后台线程里执行 mpau 子进程, 逐行收集日志并持久化到 SQLite。"""
    try:
        proc = runner.spawn_mpau(task["cmd"])
    except Exception as exc:  # noqa: BLE001
        with _tasks_lock:
            task["status"] = "failed"
            task["error"] = str(exc)
            task["finished"] = _now()
        _persist_task(task)
        return
    with _tasks_lock:
        task["proc"] = proc
        task["status"] = "running"
        task["started"] = _now()
        _persist_task(task)

    def on_line(line: str):
        append_log(task, line)
        store.append_task_log(task["id"], line)

    exit_code = runner.stream_mpau(proc, on_line)
    with _tasks_lock:
        task["exit"] = exit_code
        task["status"] = "success" if exit_code == 0 else "failed"
        task["finished"] = _now()
        task.pop("proc", None)
    if exit_code == 0:
        _mark_published_from_task(task)
    _persist_task(task)


def _mark_published_from_task(task: dict) -> None:
    """单条发布成功后写入防重发表(与批量调度一致); 试跑/草稿不记录。"""
    platform = task.get("platform", "")
    account = task.get("account", "")
    cmd = task.get("cmd") or []
    if not platform or not account or not cmd:
        return
    if isinstance(cmd, str):
        cmd = cmd.split()
    if "--dry-run" in cmd or "--draft" in cmd:
        return
    file_path = ""
    for i, part in enumerate(cmd):
        if part == "--file" and i + 1 < len(cmd):
            file_path = cmd[i + 1]
            break
    if not file_path:
        return
    sha = store.sha256_file(file_path)
    if sha:
        store.mark_published(sha, platform, account)


def _persist_task(task: dict):
    """把内存任务镜像到 SQLite(进程句柄等非持久字段剔除, 日志裁剪)。"""
    with _tasks_lock:
        data = {k: v for k, v in task.items() if k != "proc"}
    data["log"] = "\n".join((task.get("log") or [])[-600:])
    store.save_task(data)


def _restore_tasks():
    """启动时从 SQLite 恢复历史任务; 上次中断的 running/queued 标记 interrupted。"""
    global _seq
    max_n = 0
    for t in store.load_tasks():
        m = re.fullmatch(r"t(\d+)", t["id"])
        if m:
            max_n = max(max_n, int(m.group(1)))
        if t["status"] in ("running", "queued"):
            t["status"] = "interrupted"
            t["error"] = t.get("error") or "服务重启导致任务中断"
            t["finished"] = t.get("finished") or _now()
            store.save_task(t)
        t.pop("cmd_display", None)
        t.setdefault("log", [])
        with _tasks_lock:
            _tasks[t["id"]] = t
    _seq = itertools.count(max_n + 1)


def _batch_task_created(task: dict):
    """批量调度器回调: 让批量任务也出现在 Web 任务列表。"""
    t = dict(task)
    t["log"] = []
    with _tasks_lock:
        _tasks[t["id"]] = t


def create_task(kind: str, platform: str, account: str, label: str, cmd: list[str]) -> dict:
    task = {
        "id": f"t{next(_seq)}",
        "kind": kind,
        "platform": platform,
        "platform_cn": PLATFORM_CN.get(platform, platform),
        "account": account,
        "label": label,
        "cmd": list(cmd),
        "cmd_display": " ".join(cmd),
        "status": "queued",
        "log": [],
        "created": _now(),
    }
    with _tasks_lock:
        _tasks[task["id"]] = task
    _persist_task(task)
    threading.Thread(target=run_task, args=(task,), daemon=True).start()
    return task


def public_task(t: dict) -> dict:
    out = dict(t)
    out.pop("proc", None)
    out["cmd"] = t.get("cmd_display", " ".join(t.get("cmd", [])))
    out.pop("cmd_display", None)
    return out


# ---------------------------------------------------------------------------
# 账号辅助
# ---------------------------------------------------------------------------
def list_accounts(platform: str) -> list[str]:
    if not COOKIES_DIR.exists():
        return []
    pattern = f"{platform}_*.json"
    names = []
    for f in COOKIES_DIR.glob(pattern):
        name = f.stem[len(platform) + 1:]
        if name and not name.startswith("_login_qrcode"):
            names.append(name)
    return sorted(names)


def suggest_account_name(platform: str) -> str:
    """账号名留空时自动分配: {platform}1, {platform}2, ..."""
    existing = set(list_accounts(platform))
    i = 1
    while f"{platform}{i}" in existing:
        i += 1
    return f"{platform}{i}"


def latest_qrcodes() -> list[dict]:
    if not COOKIES_DIR.exists():
        return []
    files = sorted(COOKIES_DIR.glob("*_login_qrcode_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for f in files[:10]:
        m = re.fullmatch(r"(.+?)_login_qrcode_\d{8}_\d{6}", f.stem)
        if not m:
            continue
        name = m.group(1)  # e.g. douyin_shop1
        platform = next((p for p in PLATFORMS if name == p or name.startswith(p + "_")), "")
        account = name[len(platform) + 1:] if platform and name.startswith(platform + "_") else ""
        out.append({
            "name": f.name,
            "platform": platform,
            "account": account,
            "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f.stat().st_mtime)),
        })
    return out


def clear_login_qrcodes(platform: str | None = None, account: str | None = None):
    """清理登录二维码文件; 传 platform+account 时只清该账号的(多账号并发登录互不干扰)。"""
    if not COOKIES_DIR.exists():
        return
    pattern = f"{platform}_{account}_login_qrcode_*.png" if platform and account else "*_login_qrcode_*.png"
    for f in COOKIES_DIR.glob(pattern):
        try:
            f.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------
# 新版前端(Vue SPA)构建产物目录; 不存在时回退到旧版单文件模板
UI_DIST = BASE_DIR / "web" / "ui" / "dist"


@app.get("/")
def index():
    if UI_DIST.is_dir():
        return send_from_directory(UI_DIST, "index.html")
    return render_template("index.html", platforms=PLATFORMS, platform_cn=PLATFORM_CN)


@app.get("/legacy")
def legacy_index():
    """旧版单文件前端(应急回退, 验证稳定后移除)。"""
    return render_template("index.html", platforms=PLATFORMS, platform_cn=PLATFORM_CN)


@app.get("/manual")
def manual():
    """使用手册(独立静态 HTML, 局域网内任何人都可直接访问)。"""
    return send_from_directory(BASE_DIR / "docs", "使用手册.html")


@app.get("/assets/<path:name>")
def ui_assets(name: str):
    return send_from_directory(UI_DIST / "assets", name)


@app.get("/<path:path>")
def spa_fallback(path: str):
    """SPA 前端路由 fallback: dist 存在时未知前端路径一律回 index.html。"""
    if path.startswith(("api/", "qrcodes/", "package/")):
        return jsonify({"error": "not found"}), 404
    if UI_DIST.is_dir():
        if (UI_DIST / path).is_file():
            return send_from_directory(UI_DIST, path)
        return send_from_directory(UI_DIST, "index.html")
    return jsonify({"error": "not found"}), 404


@app.get("/api/platforms")
def api_platforms():
    return jsonify([{"id": p, "name": PLATFORM_CN.get(p, p)} for p in PLATFORMS])


@app.get("/api/accounts")
def api_accounts():
    platform = request.args.get("platform", "douyin")
    if platform not in PLATFORMS:
        return jsonify({"error": "unknown platform"}), 400
    account_meta.normalize_legacy_keys()  # 惰性迁移 0.1.0 版写入的 stem 键
    return jsonify({
        "platform": platform,
        "accounts": list_accounts(platform),
        "nicknames": account_meta.nicknames_for(platform),
    })


def fire_nickname_fetch(platform: str, account: str) -> None:
    """Cookie 校验通过后后台补抓平台真实昵称(fire-and-forget, 几秒级)。

    登录子进程尾部的抓取会被「完成登录」taskkill 打断(web/app.py finish-login),
    所以用独立的 `mpau <platform> nickname` 命令兜底; 失败静默, 不影响登录状态。
    """
    if platform not in CHECK_SUPPORTED:
        return

    def _run() -> None:
        try:
            subprocess.Popen(
                runner.mpau_cmd([platform, "nickname", "--account", account]),
                cwd=str(BASE_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except OSError:
            pass

    threading.Thread(target=_run, daemon=True).start()


@app.post("/api/accounts/login")
def api_login():
    data = request.get_json(force=True, silent=True) or {}
    platform = data.get("platform", "douyin")
    account = (data.get("account") or "").strip()
    if platform not in PLATFORMS:
        return jsonify({"error": "unknown platform"}), 400
    if not account:
        account = suggest_account_name(platform)  # 留空自动分配, 登录成功后显示平台真实昵称
    elif not re.fullmatch(r"[A-Za-z0-9_\-]{1,40}", account):
        return jsonify({"error": "账号名仅支持字母/数字/下划线/中划线, 长度1-40"}), 400
    headless = bool(data.get("headless"))
    clear_login_qrcodes(platform, account)  # 只清当前账号旧码, 不影响并发登录的其他账号
    cmd = [platform, "login", "--account", account]
    if headless:
        cmd.append("--headless")
    else:
        cmd.append("--headed")
    task = create_task("login", platform, account, f"登录 {PLATFORM_CN.get(platform)} 账号 {account}", cmd)
    return jsonify(public_task(task)), 202


@app.post("/api/accounts/check")
def api_check():
    data = request.get_json(force=True, silent=True) or {}
    platform = data.get("platform", "douyin")
    account = (data.get("account") or "").strip()
    if platform not in CHECK_SUPPORTED:
        return jsonify({"error": "该平台暂不支持 check"}), 400
    result = {"platform": platform, "account": account, "valid": None}

    def do_check():
        try:
            proc = subprocess.run(
                runner.mpau_cmd([platform, "check", "--account", account]),
                cwd=str(BASE_DIR), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            result["valid"] = proc.returncode == 0
            result["output"] = (proc.stdout + proc.stderr).strip()[-500:]
        except Exception as exc:  # noqa: BLE001
            result["valid"] = None
            result["error"] = str(exc)

    thread = threading.Thread(target=do_check, daemon=True)
    thread.start()
    thread.join(timeout=90)
    if result["valid"]:
        fire_nickname_fetch(platform, account)  # 手动 check 顺带补抓昵称
    return jsonify(result)


@app.post("/api/verify")
def api_verify():
    """提交短信验证码(抖音二次验证)。"""
    data = request.get_json(force=True, silent=True) or {}
    platform = data.get("platform", "douyin")
    account = (data.get("account") or "").strip()
    code = (data.get("code") or "").strip()
    if platform not in VERIFY_PLATFORMS:
        return jsonify({"error": "该平台不支持短信验证码提交"}), 400
    if not re.fullmatch(r"\d{4,8}", code):
        return jsonify({"error": "验证码格式不对"}), 400
    proc = subprocess.run(
        runner.mpau_cmd([platform, "verify", "--account", account, "--code", code]),
        cwd=str(BASE_DIR), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    return jsonify({"ok": proc.returncode == 0, "output": (proc.stdout + proc.stderr).strip()[-500:]})


@app.post("/api/accounts/finish-login")
def api_finish_login():
    """用户已在手机上完成扫码确认后调用: 直接校验 Cookie, 通过则结束登录任务。"""
    data = request.get_json(force=True, silent=True) or {}
    platform = data.get("platform", "douyin")
    account = (data.get("account") or "").strip()
    if platform not in CHECK_SUPPORTED:
        return jsonify({"error": "该平台不支持 Cookie 校验"}), 400

    result: dict[str, Any] = {"valid": None}

    def do_check():
        try:
            proc = subprocess.run(
                runner.mpau_cmd([platform, "check", "--account", account]),
                cwd=str(BASE_DIR), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=25,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            result["valid"] = proc.returncode == 0
        except Exception as exc:  # noqa: BLE001
            result["valid"] = None
            result["error"] = str(exc)

    thread = threading.Thread(target=do_check, daemon=True)
    thread.start()
    thread.join(timeout=30)
    if thread.is_alive():
        return jsonify({"ok": False, "valid": None, "message": "Cookie 校验超时, 请稍后重试"}), 200

    valid = result["valid"]
    if not valid:
        return jsonify({"ok": False, "valid": False, "message": "Cookie 还未生效, 请确认已在手机上完成登录确认"}), 200

    # 结束该账号的登录任务
    with _tasks_lock:
        for t in _tasks.values():
            if t["kind"] == "login" and t["platform"] == platform and t["account"] == account and t["status"] in ("queued", "running"):
                p = t.get("proc")
                if p and p.poll() is None:
                    subprocess.run(
                        ["taskkill", "/PID", str(p.pid), "/T", "/F"],
                        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                t["status"] = "success"
                t["finished"] = _now()
                append_log(t, "手机端登录已确认, Cookie 校验通过, 登录任务结束")
                _persist_task(t)
    clear_login_qrcodes(platform, account)
    fire_nickname_fetch(platform, account)  # 登录确认后后台补抓平台真实昵称
    return jsonify({"ok": True, "valid": True})


@app.post("/api/accounts/logout")
def api_logout():
    """退出/删除账号: 清除本地登录 Cookie 与昵称元数据, 回到未登录状态。"""
    data = request.get_json(force=True, silent=True) or {}
    platform = data.get("platform", "douyin")
    account = (data.get("account") or "").strip()
    if platform not in PLATFORMS:
        return jsonify({"error": "unknown platform"}), 400
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,40}", account):
        return jsonify({"error": "账号名仅支持字母/数字/下划线/中划线"}), 400

    removed = []
    targets = [
        COOKIES_DIR / f"{platform}_{account}.json",
        COOKIES_DIR / f"{account}_verify_code.json",  # 抖音短信验证码残留文件
    ]
    for path in targets:
        if path.is_file():
            try:
                path.unlink()
                removed.append(path.name)
            except OSError as exc:
                return jsonify({"error": f"删除 {path.name} 失败: {exc}"}), 500
    account_meta.remove_nickname(platform, account)
    if not removed:
        return jsonify({"ok": True, "removed": [], "message": f"账号 {account} 本来就没有登录记录"})
    return jsonify({"ok": True, "removed": removed, "message": f"已退出账号 {account}, 本地登录状态已清除"})


@app.get("/api/drives")
def api_drives():
    """返回本机可用盘符, 供文件浏览切换。"""
    drives = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        root = f"{letter}:\\"
        if os.path.exists(root):
            entry = {"letter": f"{letter}:", "root": root}
            try:
                usage = shutil.disk_usage(root)
                entry["free"] = usage.free
                entry["total"] = usage.total
            except OSError:
                pass
            drives.append(entry)
    return jsonify(drives)


@app.get("/api/qrcodes")
def api_qrcodes():
    return jsonify(latest_qrcodes())


@app.get("/qrcodes/<path:name>")
def qrcode_file(name: str):
    """登录二维码图片。白名单文件名, 防止借该路由下载 cookies/ 下的会话 Cookie/调试快照。"""
    if not re.fullmatch(r"[A-Za-z0-9_\-]+_login_qrcode_\d{8}_\d{6}\.png", name):
        return jsonify({"error": "not found"}), 404
    return send_from_directory(COOKIES_DIR, name)


@app.get("/package/<path:name>")
def package_file(name: str):
    """安装包下载: mpau.zip / install.ps1"""
    return send_from_directory(PACKAGE_DIR, name)


@app.get("/api/files")
def api_files():
    raw = request.args.get("path", str(DEFAULT_FILES_ROOT))
    path = Path(raw).expanduser()
    # Windows 盘符归一化: "E" / "E:" -> "E:\\"
    if os.name == "nt" and re.fullmatch(r"[A-Za-z]:?", str(path)):
        path = Path(str(path).rstrip(":") + ":\\")
    if not path.exists():
        return jsonify({"error": f"路径不存在: {raw}", "cwd": str(path.parent if path.parent.exists() else path)}), 400
    if path.is_file():
        path = path.parent
    entries = []
    try:
        for item in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            if item.name.startswith("."):
                continue
            try:
                size = item.stat().st_size if item.is_file() else None
            except OSError:
                size = None
            entries.append({"name": item.name, "dir": item.is_dir(), "size": size})
    except PermissionError:
        return jsonify({"error": "无权限访问该目录"}), 403
    parent = None if path.parent == path else str(path.parent)  # 盘符根不再显示上级
    return jsonify({"path": str(path), "parent": parent, "entries": entries})


@app.get("/api/tasks")
def api_tasks():
    items = store.load_tasks()
    with _tasks_lock:
        live = {t["id"]: t for t in _tasks.values()}
    for it in items:
        it.pop("cmd_display", None)
        lv = live.get(it["id"])
        if not lv:
            continue
        # 内存副本只对"自己派发的任务"权威(create_task 起的登录/单发, 由 run_task 维护)。
        # 批量任务由调度器直接写 SQLite(只登记了一次 status=running), 内存副本永远不更新,
        # 若无条件覆盖会把 DB 里的 success/failed 显示成"运行中"。
        db_terminal = it.get("status") in TERMINAL_TASK_STATUSES
        live_terminal = lv.get("status") in TERMINAL_TASK_STATUSES
        if live_terminal or not db_terminal:
            it["status"] = lv["status"]
            it["error"] = lv.get("error", it.get("error", ""))
            it["exit"] = lv.get("exit", it.get("exit"))
        # 日志取较长的一份: 批量任务的内存 log 恒为空([]), 真日志在 SQLite
        live_log = lv.get("log") or []
        db_log = it.get("log") or []
        it["log"] = (live_log if len(live_log) >= len(db_log) else db_log)[-MAX_LOG_LINES:]
    return jsonify({"tasks": items})


@app.post("/api/tasks")
def api_create_task():
    data = request.get_json(force=True, silent=True) or {}
    platform = data.get("platform", "douyin")
    account = (data.get("account") or "").strip()
    content_type = data.get("content_type", "video")  # video | note
    if platform not in PLATFORMS:
        return jsonify({"error": "unknown platform"}), 400
    if not account:
        return jsonify({"error": "请选择账号"}), 400
    if account not in list_accounts(platform):
        available = list_accounts(platform)
        hint = ""
        if available:
            hint = f"; 当前 {PLATFORM_CN[platform]} 已登录账号: {', '.join(available)}"
        return jsonify({"error": f"账号 {account} 没有本地 Cookie, 请先登录{hint}"}), 400

    # 防重发: 同一视频(sha256)同一平台账号已发布过则拦截(试跑不拦)
    if content_type == "video" and not data.get("dry_run"):
        file_path = str(data.get("file") or "").strip()
        if file_path:
            sha = store.sha256_file(file_path)
            if sha:
                when = store.published_at(sha, platform, account)
                if when:
                    return jsonify({"error": f"该视频已在 {PLATFORM_CN[platform]} 账号 {account} 发布过({when}), 已拦截重复发布; 确需重发请更换视频文件"}), 400

    opts = PLATFORM_OPTS[platform]
    if content_type == "note":
        if not opts.get("note"):
            return jsonify({"error": f"{PLATFORM_CN[platform]} 不支持图文"}), 400
        images = [p.strip() for p in data.get("images", []) if p.strip()]
        if not images:
            return jsonify({"error": "请填写至少一张图片路径"}), 400
        for p in images:
            if not Path(p).is_file():
                return jsonify({"error": f"图片不存在: {p}"}), 400
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"error": "请填写标题"}), 400
        cmd = [platform, "upload-note", "--account", account, "--title", title]
        for img in images:
            cmd += ["--images", img]
        if data.get("note"):
            cmd += ["--note", data["note"]]
        if data.get("tags"):
            cmd += ["--tags", data["tags"]]
        label = f"图文 {title[:20]} ({len(images)}图)"
    else:
        file_path = (data.get("file") or "").strip()
        if not file_path or not Path(file_path).is_file():
            return jsonify({"error": f"视频文件不存在: {file_path}"}), 400
        title = (data.get("title") or "").strip()
        if opts.get("title_required") and not title:
            return jsonify({"error": "该平台需要标题"}), 400
        if opts.get("desc_required") and not (data.get("desc") or "").strip():
            return jsonify({"error": "该平台需要描述"}), 400
        cmd = [platform, "upload-video", "--account", account, "--file", file_path]
        if title:
            cmd += ["--title", title]
        if data.get("desc") and not opts.get("no_desc"):
            cmd += ["--desc", data["desc"]]
        if data.get("tags"):
            cmd += ["--tags", data["tags"]]
        if data.get("schedule"):
            cmd += ["--schedule", data["schedule"]]
        if data.get("thumbnail"):
            cmd += ["--thumbnail", data["thumbnail"]]
        if opts.get("goods") == "product":
            if data.get("product_link"):
                cmd += ["--product-link", data["product_link"]]
            if data.get("product_title"):
                cmd += ["--product-title", data["product_title"]]
        elif opts.get("goods") == "goods_id":
            if data.get("goods_id"):
                cmd += ["--goods-id", str(data["goods_id"])]
        if opts.get("tid"):
            cmd += ["--tid", str(int(data.get("tid") or 0))]
        if opts.get("draft") and data.get("draft"):
            cmd.append("--draft")
        if opts.get("dry_run") and data.get("dry_run"):
            cmd.append("--dry-run")
        label = f"视频 {title[:20] or Path(file_path).name}"
    if data.get("headless"):
        cmd.append("--headless")
    else:
        cmd.append("--headed")
    task = create_task("upload", platform, account, label, cmd)
    return jsonify(public_task(task)), 202


@app.post("/api/tasks/<task_id>/cancel")
def api_cancel_task(task_id: str):
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        return jsonify({"error": "task not found"}), 404
    proc = task.get("proc")
    if proc and proc.poll() is None:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        with _tasks_lock:
            task["status"] = "canceled"
            task["finished"] = _now()
        append_log(task, "任务已取消")
        _persist_task(task)
        return jsonify({"ok": True})
    with _tasks_lock:
        if task["status"] in ("queued", "interrupted"):
            task["status"] = "canceled"
            task["finished"] = _now()
    append_log(task, "任务已取消")
    _persist_task(task)
    return jsonify({"ok": False, "message": "任务不在运行中"}) if task.get("status") != "canceled" else jsonify({"ok": True})


# ---------------------------------------------------------------------------
# 设置(LLM / 调度风控)
# ---------------------------------------------------------------------------
@app.get("/api/stats/today")
def api_stats_today():
    """今日数据看板(右侧统计卡)。"""
    return jsonify(store.today_stats())


@app.get("/api/settings")
def api_get_settings():
    cfg = load_config()
    llm = dict(cfg["llm"])
    llm["api_key"] = mask_key(llm["api_key"])
    return jsonify({"llm": llm, "scheduler": cfg["scheduler"]})


@app.post("/api/settings")
def api_set_settings():
    data = request.get_json(force=True, silent=True) or {}
    cfg = load_config()
    llm = data.get("llm") or {}
    sched = data.get("scheduler") or {}
    if not isinstance(llm, dict) or not isinstance(sched, dict):
        return jsonify({"error": "参数格式错误"}), 400

    for key in ("base_url", "model"):
        if key in llm and isinstance(llm[key], str):
            cfg["llm"][key] = llm[key].strip()
    for key in ("timeout", "max_tokens", "n_candidates"):
        if key in llm and isinstance(llm[key], int) and llm[key] > 0:
            cfg["llm"][key] = llm[key]
    api_key = str(llm.get("api_key") or "").strip()
    if api_key and "*" not in api_key:  # 未填/掩码值(含*)不覆盖真实 Key
        cfg["llm"]["api_key"] = api_key

    limits = cfg["scheduler"]
    if "interval_min" in sched and isinstance(sched["interval_min"], (int, float)):
        cfg["scheduler"]["interval_min"] = min(
            max(float(sched["interval_min"]), float(limits.get("min_interval_min", 3))),
            float(limits.get("max_interval_min", 60)),
        )
    if "daily_cap" in sched and isinstance(sched["daily_cap"], int):
        cfg["scheduler"]["daily_cap"] = min(
            max(sched["daily_cap"], int(limits.get("min_daily_cap", 1))),
            int(limits.get("max_daily_cap", 100)),
        )
    if "max_concurrent" in sched and isinstance(sched["max_concurrent"], int):
        cfg["scheduler"]["max_concurrent"] = min(max(sched["max_concurrent"], 1), 8)
    # 平台每日上限: {platform: int}; 空值/非法值忽略, 不设的字段保留原值
    if isinstance(sched.get("platform_daily_caps"), dict):
        caps = dict(cfg["scheduler"].get("platform_daily_caps") or {})
        for platform, value in sched["platform_daily_caps"].items():
            try:
                caps[platform] = min(max(int(value), 1), 100)
            except (TypeError, ValueError):
                continue
        cfg["scheduler"]["platform_daily_caps"] = caps
    merged = save_config(cfg)
    llm_out = dict(merged["llm"])
    llm_out["api_key"] = mask_key(llm_out["api_key"])
    return jsonify({"llm": llm_out, "scheduler": merged["scheduler"]})


@app.post("/api/settings/test")
def api_settings_test():
    """用表单参数试连 LLM(Key 为掩码值时沿用已保存的真实 Key)。
    防 SSRF: 只有显式提交了新 Key 才允许同时改 base_url;
    沿用已保存 Key 时强制使用已保存的 base_url, 避免真实 Key 被发到攻击者服务器。"""
    data = request.get_json(force=True, silent=True) or {}
    llm = data.get("llm") or {}
    probe = dict(load_config()["llm"])
    if isinstance(llm, dict):
        api_key = str(llm.get("api_key") or "").strip()
        if api_key and "*" not in api_key:
            probe["api_key"] = api_key
            for key in ("base_url", "model"):
                if isinstance(llm.get(key), str) and llm[key].strip():
                    probe[key] = llm[key].strip()
        elif isinstance(llm.get("model"), str) and llm["model"].strip():
            probe["model"] = llm["model"].strip()
    base_url = str(probe.get("base_url") or "")
    if base_url and not base_url.startswith(("http://", "https://")):
        return jsonify({"ok": False, "message": "base_url 必须是 http(s) 地址"}), 400
    try:
        from pipeline.copy_engine import _call_llm

        _call_llm([{"role": "user", "content": "只回复两个字: 正常"}], probe)
        return jsonify({"ok": True, "message": f"连接成功 (model={probe.get('model')}, {probe.get('base_url')})"})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "message": str(exc)})


# ---------------------------------------------------------------------------
# AI 文案(单视频多平台 / 校验)
# ---------------------------------------------------------------------------
@app.post("/api/copy/generate")
def api_copy_generate():
    data = request.get_json(force=True, silent=True) or {}
    platforms = data.get("platforms") or CORE_PLATFORMS
    platforms = [p for p in platforms if p in PLATFORMS]
    if not platforms:
        return jsonify({"error": "请选择至少一个平台"}), 400
    base_title = str(data.get("title") or "").strip()
    if not base_title:
        return jsonify({"error": "人工标题为空, 无法生成"}), 400
    base = {
        "title": base_title,
        "brief": str(data.get("brief") or "").strip(),
        "desc": str(data.get("desc") or "").strip(),
        "tags": rules.clean_tags(data.get("tags")),
        "goods": {
            "link": str(data.get("product_link") or "").strip(),
            "title": str(data.get("product_title") or "").strip(),
            "id": str(data.get("goods_id") or "").strip(),
        },
    }
    n = int(data.get("n") or load_config()["llm"]["n_candidates"])
    result = copy_engine.generate_copy(
        platforms,
        base,
        n=n,
        with_desc=bool(data.get("with_desc", True)),
        with_tags=bool(data.get("with_tags", True)),
    )
    return jsonify(result)


@app.get("/api/copy/rules")
def api_copy_rules():
    """各平台文案规则(供前端提示字数上限/违禁词)。"""
    out = {}
    for p in PLATFORMS:
        rule = rules.rule_for(p)
        out[p] = {
            "cn": rule["cn"],
            "title_max": rule.get("title_max") or 0,
            "title_min": rule.get("title_min") or 0,
            "banned": rule.get("banned") or [],
            "goods": rule.get("goods"),
            "notes": rule.get("notes", ""),
        }
    return jsonify(out)


@app.post("/api/copy/validate")
def api_copy_validate():
    data = request.get_json(force=True, silent=True) or {}
    platform = data.get("platform", "")
    title = str(data.get("title") or "").strip()
    if platform not in PLATFORMS:
        return jsonify({"error": "unknown platform"}), 400
    if not title:
        return jsonify({"ok": False, "issues": [{"level": "error", "msg": "标题为空"}]})
    issues = rules.validate_title(platform, title)
    return jsonify({"ok": not any(i["level"] == "error" for i in issues), "issues": issues})


# ---------------------------------------------------------------------------
# 批量发布(/api/batch/*)
# ---------------------------------------------------------------------------
@app.post("/api/batch/scan")
def api_batch_scan():
    data = request.get_json(force=True, silent=True) or {}
    folder = str(data.get("dir") or "").strip()
    if not folder:
        return jsonify({"error": "请选择文件夹"}), 400
    try:
        result = batch_runner.scan_and_register(folder, data.get("batch_id"))
    except (RuntimeError, FileNotFoundError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


@app.post("/api/batch/import")
def api_batch_import():
    data = request.get_json(force=True, silent=True) or {}
    csv_path = str(data.get("csv") or "").strip()
    if not csv_path:
        return jsonify({"error": "请提供 CSV 路径"}), 400
    try:
        result = batch_runner.import_and_register(csv_path, data.get("batch_id"))
    except (RuntimeError, FileNotFoundError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


@app.post("/api/batch/videos/add")
def api_batch_video_add():
    """选择单条视频: 登记单个视频到批次(无批次则新建; 已在本批次则 added=False)。"""
    data = request.get_json(force=True, silent=True) or {}
    path = str(data.get("path") or "").strip()
    if not path:
        return jsonify({"error": "请选择视频文件"}), 400
    batch_id = str(data.get("batch_id") or "").strip() or None
    try:
        result = batch_runner.add_video_and_register(path, batch_id)
    except (RuntimeError, FileNotFoundError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(result)


@app.get("/api/batch/videos")
def api_batch_videos():
    """当前批次的视频列表(批次登记过视频清单时只返回该批次的, 实现"一批=一个文件夹")。"""
    batch_id = request.args.get("batch_id", "")
    video_ids = store.get_batch_videos(batch_id) if batch_id else []
    videos = store.list_videos()
    if batch_id:
        ids = set(video_ids)
        videos = [v for v in videos if v["id"] in ids]
    video_id = request.args.get("video_id", type=int)
    if video_id:
        videos = [v for v in videos if v["id"] == video_id]
    return jsonify({"videos": videos, "batch_id": batch_id})


@app.get("/api/batch/videos/csv")
def api_batch_videos_csv():
    """把当前批次视频清单导出为 CSV(每视频一行), 方便离线续填。"""
    from pipeline.scanner import export_csv
    batch_id = request.args.get("batch_id", "")
    if batch_id:
        ids = set(store.get_batch_videos(batch_id))
        videos = [v for v in store.list_videos() if v["id"] in ids]
    else:
        videos = store.list_videos()
    reports_dir = store.DATA_DIR / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = export_csv(videos, reports_dir / "videos.csv")
    return send_from_directory(reports_dir, Path(path).name, as_attachment=True)


@app.post("/api/batch/videos/<int:video_id>")
def api_batch_video_update(video_id: int):
    data = request.get_json(force=True, silent=True) or {}
    fields = {k: data.get(k) for k in ("base_title", "base_desc", "base_tags", "schedule", "cover", "goods_json") if data.get(k) is not None}
    if not fields:
        return jsonify({"error": "没有可更新的字段"}), 400
    return jsonify(batch_runner.update_video_fields(video_id, fields))


@app.post("/api/batch/plan")
def api_batch_plan():
    data = request.get_json(force=True, silent=True) or {}
    batch_id = str(data.get("batch_id") or "").strip()
    if not batch_id:
        return jsonify({"error": "缺少 batch_id"}), 400
    platforms = data.get("platforms") or CORE_PLATFORMS
    platforms = [p for p in platforms if p in PLATFORMS]
    if not platforms:
        return jsonify({"error": "请选择至少一个平台"}), 400
    accounts = data.get("accounts") or {}
    if isinstance(accounts, str):
        from pipeline.planner import parse_account_map
        accounts = parse_account_map(accounts)
    missing = []
    for p in platforms:
        acc = (accounts or {}).get(p, "")
        if isinstance(acc, str):
            acc = [acc] if acc else []
        acc_list = [str(a) for a in acc if a]
        if not acc_list:
            missing.append(f"{PLATFORM_CN.get(p, p)} 未选择账号")
            continue
        for a in acc_list:
            if a not in list_accounts(p):
                missing.append(f"{PLATFORM_CN.get(p, p)} 账号 {a} 未登录(请先在账号页扫码)")
    if missing:
        return jsonify({"error": "; ".join(missing)}), 400

    video_ids = data.get("video_ids")
    if video_ids is None:
        # 兜底: 未指定视频时用批次登记的视频清单(再兜底全部)
        video_ids = store.get_batch_videos(batch_id) or [v["id"] for v in store.list_videos()]
    videos = [v for v in store.list_videos() if v["id"] in video_ids]
    if not videos:
        return jsonify({"error": "没有可用的视频, 请先扫描文件夹"}), 400
    result = batch_runner.plan_batch(batch_id, [v["id"] for v in videos], platforms, accounts)
    return jsonify(result)


@app.get("/api/batch/brief")
def api_batch_brief_get():
    batch_id = request.args.get("batch_id", "")
    if not batch_id:
        return jsonify({"error": "缺少 batch_id"}), 400
    return jsonify({"batch_id": batch_id, "brief": store.get_batch_brief(batch_id)})


@app.post("/api/batch/brief")
def api_batch_brief_set():
    data = request.get_json(force=True, silent=True) or {}
    batch_id = str(data.get("batch_id") or "").strip()
    if not batch_id:
        return jsonify({"error": "缺少 batch_id"}), 400
    brief = str(data.get("brief") or "")[:500]
    store.set_batch_brief(batch_id, brief)
    return jsonify({"batch_id": batch_id, "brief": brief})


_batch_gens: dict[str, dict] = {}  # batch_id -> 生成进度信息
_batch_gens_lock = threading.Lock()


@app.post("/api/batch/generate")
def api_batch_generate():
    data = request.get_json(force=True, silent=True) or {}
    batch_id = str(data.get("batch_id") or "").strip()
    if not batch_id:
        return jsonify({"error": "缺少 batch_id"}), 400
    with _batch_gens_lock:
        info = _batch_gens.get(batch_id)
        if info and info.get("running"):
            return jsonify({"error": "该批次正在生成文案中, 请稍候"}), 409
        info = {"running": True, "total": 0, "done": 0, "failed": 0, "current": "", "result": None, "error": ""}
        _batch_gens[batch_id] = info
    platforms = [p for p in (data.get("platforms") or []) if p in PLATFORMS] or None
    brief = str(data.get("brief") or "")[:500]
    if brief:
        store.set_batch_brief(batch_id, brief)

    def _run():
        def on_progress(done, failed, total, current):
            info.update(done=done, failed=failed, total=total, current=current or "")

        try:
            result = batch_runner.generate_batch(
                batch_id, platforms,
                with_desc=bool(data.get("with_desc", True)),
                with_tags=bool(data.get("with_tags", True)),
                with_goods_title=bool(data.get("with_goods_title", False)),
                brief=brief,
                on_progress=on_progress,
            )
            info["result"] = result
        except Exception as exc:  # noqa: BLE001
            info["error"] = str(exc)
        finally:
            info["running"] = False

    threading.Thread(target=_run, daemon=True, name=f"batchgen-{batch_id}").start()
    return jsonify({"batch_id": batch_id, "started": True})


@app.get("/api/batch/generate-progress")
def api_batch_generate_progress():
    batch_id = request.args.get("batch_id", "")
    with _batch_gens_lock:
        info = _batch_gens.get(batch_id)
        return jsonify(dict(info) if info else {"running": False, "total": 0, "done": 0, "failed": 0, "current": ""})


@app.post("/api/batch/delete")
def api_batch_delete():
    data = request.get_json(force=True, silent=True) or {}
    batch_id = str(data.get("batch_id") or "").strip()
    if not batch_id:
        return jsonify({"error": "缺少 batch_id"}), 400
    batch_runner.stop_batch(batch_id)  # 有调度器运行则先停
    store.delete_batch(batch_id)
    with _batch_gens_lock:
        _batch_gens.pop(batch_id, None)
    return jsonify({"ok": True, "batch_id": batch_id})


@app.get("/api/batch/items")
def api_batch_items():
    batch_id = request.args.get("batch_id", "")
    items = store.list_items(batch_id or None)
    videos = {v["id"]: v for v in store.list_videos()}
    out = []
    for it in items:
        pub = planner.public_item(it, videos.get(it["video_id"]))
        raw = it.get("candidates_json") or "[]"
        try:
            pub["candidates"] = json.loads(raw)
        except ValueError:
            pub["candidates"] = []
        out.append(pub)
    return jsonify({"items": out})


@app.post("/api/batch/items/<int:item_id>")
def api_batch_item_update(item_id: int):
    """更新条目。文案字段(标题/描述/标签/定时/账号/状态)始终生效;

    商品字段按作用域分流:
      - 商品ID(g_id) / 商品名称(g_name, 快手用) → **仅本条目**(各平台/账号各绑各的)
      - 商品链接/短标题 → 本条目 + 视频级默认值(供新建条目播种)
    早期实现一进商品分支就 return, 导致同请求里的文案字段被静默丢弃。
    """
    item = store.get_item(item_id)
    if not item:
        return jsonify({"error": "条目不存在"}), 404
    data = request.get_json(force=True, silent=True) or {}

    # 1) 文案/状态字段(不再因商品字段而跳过)
    fields = {}
    for key in ("title", "desc", "schedule", "account"):
        if key in data and isinstance(data[key], str):
            fields[key] = data[key].strip()
    if "tags" in data:
        fields["tags"] = ",".join(rules.clean_tags(data["tags"]))
    if "goods_json" in data and isinstance(data["goods_json"], dict):
        fields["goods_json"] = json.dumps(data["goods_json"], ensure_ascii=False)
    if "status" in data and data["status"] in ("draft", "approved", "needs_manual"):
        fields["status"] = data["status"]
    if fields:
        batch_runner.set_item_content(item_id, fields)

    # 2) 商品字段
    if any(k in data for k in ("g_link", "g_title", "g_id", "g_name")):
        goods: dict = {}
        try:
            goods = json.loads(item.get("goods_json") or "{}")
        except ValueError:
            goods = {}
        if "g_link" in data:
            goods["link"] = str(data["g_link"] or "").strip()
        if "g_title" in data:
            goods["title"] = str(data["g_title"] or "").strip()
        if "g_id" in data:
            goods["id"] = str(data["g_id"] or "").strip()
        if "g_name" in data:
            # 快手按商品名称关联商品(名称需与快手小店一致)
            goods["name"] = str(data["g_name"] or "").strip()
        updated = batch_runner.update_item_goods(item_id, goods)
        # 链接/短标题是视频级默认值: 同步回视频, 让后续新建条目继承
        # (商品ID/商品名称是条目级, 刻意不回写, 避免扩散到其他平台账号)
        if updated and ("g_link" in data or "g_title" in data):
            batch_runner.update_video_fields(
                updated["video_id"], {"goods_json": updated.get("goods_json", "")}
            )

    updated = store.get_item(item_id)
    video = store.get_video(updated["video_id"]) if updated else None
    return jsonify(planner.public_item(updated, video) if updated else {})


@app.post("/api/batch/items/<int:item_id>/regenerate")
def api_batch_item_regenerate(item_id: int):
    item = store.get_item(item_id)
    if not item:
        return jsonify({"error": "条目不存在"}), 404
    video = store.get_video(item["video_id"])
    if not video:
        return jsonify({"error": "视频记录不存在"}), 404
    brief = store.get_batch_brief(item["batch_id"])
    if not video.get("base_title") and not brief:
        return jsonify({"error": "该视频缺人工标题且批次没有 AI 提示词, 请先填写"}), 400
    data = request.get_json(force=True, silent=True) or {}
    goods = item.get("goods_json") or "{}"
    if isinstance(goods, str):
        try:
            goods = json.loads(goods)
        except ValueError:
            goods = {}
    base = {
        "title": (video.get("base_title") or "").strip(),
        "desc": video.get("base_desc", ""),
        "tags": video.get("base_tags", ""),
        "goods": goods,
        "brief": brief,
    }
    result = copy_engine.generate_one(
        item["platform"], base, n=int(data.get("n") or 3),
        with_desc=bool(data.get("with_desc", True)),
        with_tags=bool(data.get("with_tags", True)),
    )
    if result.get("error"):
        return jsonify({"error": result["error"]}), 502
    cands = result.get("candidates") or []
    first = cands[0] if cands else {}
    store.update_item(
        item_id,
        title=first.get("title", ""),
        desc=first.get("desc", ""),
        tags=",".join(first.get("tags") or []),
        candidates_json=json.dumps(cands, ensure_ascii=False),
    )
    return jsonify(result)


@app.post("/api/batch/approve")
def api_batch_approve():
    data = request.get_json(force=True, silent=True) or {}
    batch_id = str(data.get("batch_id") or "").strip()
    if not batch_id:
        return jsonify({"error": "缺少 batch_id"}), 400
    approved = bool(data.get("approved", True))
    item_ids = data.get("item_ids")
    if item_ids:
        items = [it for it in store.list_items(batch_id) if it["id"] in item_ids]
    else:
        items = [it for it in store.list_items(batch_id) if it["status"] in ("draft", "needs_manual")]
    n = batch_runner.approve_items([it["id"] for it in items], approved)
    return jsonify({"batch_id": batch_id, "approved": n})


@app.post("/api/batch/run")
def api_batch_run():
    data = request.get_json(force=True, silent=True) or {}
    batch_id = str(data.get("batch_id") or "").strip()
    if not batch_id:
        return jsonify({"error": "缺少 batch_id"}), 400
    cfg = load_config()["scheduler"]
    interval = float(data.get("interval_min") or cfg["interval_min"])
    interval = min(max(interval, cfg["min_interval_min"]), cfg["max_interval_min"])
    result = batch_runner.run_batch(
        batch_id,
        interval_min=interval,
        daily_cap=int(data.get("daily_cap") or cfg["daily_cap"]),
        daily_caps=cfg.get("platform_daily_caps") or {},
        max_concurrent=min(max(int(data.get("max_concurrent") or cfg["max_concurrent"]), 1), 8),
        dry_run=bool(data.get("dry_run")),
        draft=bool(data.get("draft")),
        headless=bool(data.get("headless")),
        force=bool(data.get("force")),
        on_task_created=_batch_task_created,
    )
    if result.get("error"):
        return jsonify(result), 400
    return jsonify(result)


@app.get("/api/batch/quota")
def api_batch_quota():
    """运行前额度预览: 各平台已批准数 vs 今日上限。"""
    batch_id = request.args.get("batch_id", "")
    if not batch_id:
        return jsonify({"error": "缺少 batch_id"}), 400
    cfg = load_config()["scheduler"]
    return jsonify(batch_runner.quota_info(batch_id, cfg.get("platform_daily_caps") or {}))


@app.post("/api/batch/stop")
def api_batch_stop():
    data = request.get_json(force=True, silent=True) or {}
    batch_id = str(data.get("batch_id") or "").strip()
    if not batch_id:
        return jsonify({"error": "缺少 batch_id"}), 400
    return jsonify(batch_runner.stop_batch(batch_id))


@app.get("/api/batch/status")
def api_batch_status():
    batch_id = request.args.get("batch_id", "")
    if not batch_id:
        return jsonify({"error": "缺少 batch_id"}), 400
    return jsonify(batch_runner.batch_status(batch_id))


@app.get("/api/batch/batches")
def api_batch_batches():
    return jsonify({"batches": batch_runner.list_batches()})


@app.post("/api/batch/items/<int:item_id>/retry")
def api_batch_item_retry(item_id: int):
    try:
        item = batch_runner.retry_item(item_id)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 400
    video = store.get_video(item["video_id"])
    return jsonify(planner.public_item(item, video))


@app.get("/api/batch/report")
def api_batch_report():
    batch_id = request.args.get("batch_id", "")
    if not batch_id:
        return jsonify({"error": "缺少 batch_id"}), 400
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", batch_id):
        return jsonify({"error": "batch_id 格式不正确"}), 400
    reports_dir = store.DATA_DIR / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = batch_runner.report_csv(batch_id, reports_dir / f"{batch_id}.csv")
    return send_from_directory(reports_dir, Path(path).name, as_attachment=True)


if __name__ == "__main__":
    port = int(os.getenv("MPAU_WEB_PORT", "8898"))
    host = os.getenv("MPAU_WEB_HOST", "127.0.0.1")
    if not (BASE_DIR / "mpau_cli.py").is_file():
        raise SystemExit(f"未找到 mpau 入口: {BASE_DIR / 'mpau_cli.py'}, 安装包可能损坏")
    store.init_db()
    _restore_tasks()
    local = host in ("127.0.0.1", "localhost", "::1")
    display_host = "127.0.0.1" if local else host
    print(f"mpau Web 管理后台: http://{display_host}:{port}/?token={web_token()}")
    if not local:
        print("⚠️ 局域网模式: 任何拿到上面令牌链接的人都能操作本机账号, 请勿外发, 不要暴露公网")
    if os.getenv("MPAU_TRAY") == "1":
        try:
            import tray  # web/ 同目录模块(脚本方式启动时 sys.path 已含本目录)
            if tray.start_tray(open_ui_window, shutdown_server, BASE_DIR / "assets" / "icon.png"):
                print("系统托盘已启用: 右键托盘图标可打开主界面或退出")
        except Exception:  # noqa: BLE001 - 托盘失败不影响主服务
            pass
    app.run(host=host, port=port, debug=False, threaded=True)
