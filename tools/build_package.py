# -*- coding: utf-8 -*-
"""重建 package/mpau.zip 单分发包(项目代码 + 浏览器内核, 开箱即用)。

- 项目源码: 排除 .venv/cookies/.git/pycache/data/package/logs/媒体文件
- 浏览器内核: 本机 %LOCALAPPDATA%/ms-playwright, 打进 zip 内 ms-playwright/ 前缀,
  安装脚本会解压到目标机同路径, 免在线下载(约 700MB)
"""
import json
import os
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "package"

SKIP_ROOT_DIRS = {"data", "package", "logs", "cookies"}   # 仅排除项目根级目录(cookies 含登录凭据, 严禁打包)
SKIP_ANY_DIRS = {".venv", ".git", "__pycache__", "node_modules", ".pytest_cache"}
SKIP_FILES = {"*.pyc", "*.zip", "*.mp4", "*.mov", "*.mkv", "*.flv", "*.wmv", "*.webm", "*.avi", "*.png", "*.jpg", "*.jpeg", "*.webp"}


def _skip(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if rel.parts and rel.parts[0] in SKIP_ROOT_DIRS:
        return True
    for part in path.parts:
        if part in SKIP_ANY_DIRS:
            return True
    for pat in SKIP_FILES:
        if path.match(pat):
            return True
    return False


def expected_revisions() -> dict[str, str]:
    """patchright 期望的浏览器 build 号: {"chromium": "1208", "chromium-headless-shell": "1208"}。"""
    browsers_json = (
        ROOT / ".venv" / "Lib" / "site-packages" / "patchright" / "driver" / "package" / "browsers.json"
    )
    data = json.loads(browsers_json.read_text(encoding="utf-8"))
    return {b["name"]: str(b["revision"]) for b in data["browsers"] if b.get("installByDefault")}


def build_colleague() -> Path:
    """项目源码 + 与依赖匹配的浏览器内核, 打进单个 mpau.zip。"""
    out = PACKAGE / "mpau.zip"
    if out.exists():
        out.unlink()
    revs = expected_revisions()
    keep = {f"chromium-{revs['chromium']}", f"chromium_headless_shell-{revs['chromium-headless-shell']}"}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(ROOT.rglob("*")):
            if p.is_dir() or _skip(p):
                continue
            zf.write(p, p.relative_to(ROOT))
        browsers = Path(os.getenv("LOCALAPPDATA", "")) / "ms-playwright"
        if browsers.is_dir():
            picked = []
            for d in sorted(browsers.iterdir()):
                if not d.is_dir():
                    continue
                # 只打期望版本的 chromium/headless shell + ffmpeg/winldd 公共组件
                if d.name not in keep and not re.match(r"^(ffmpeg|winldd)-", d.name):
                    continue
                picked.append(d.name)
                for p in sorted(d.rglob("*")):
                    if p.is_dir():
                        continue
                    zf.write(p, Path("ms-playwright") / p.relative_to(browsers))
            print(f"  打包内核: {sorted(picked)}")
        else:
            print("  ⚠️ 未找到 ms-playwright 目录, 包内不含浏览器内核")
    return out


def verify_contains(zip_path: Path, names: list[str]) -> bool:
    with zipfile.ZipFile(zip_path) as zf:
        have = set(zf.namelist())
    missing = [n for n in names if n not in have]
    if missing:
        print(f"  ⚠️ {zip_path.name} 缺少: {missing}")
        return False
    return True


def verify_kernel_revision() -> bool:
    """内置内核 build 应与 .venv 里 patchright 期望的 revision 一致, 否则无 Chrome 兜底会失效。"""
    browsers_json = (
        ROOT / ".venv" / "Lib" / "site-packages" / "patchright" / "driver" / "package" / "browsers.json"
    )
    try:
        data = json.loads(browsers_json.read_text(encoding="utf-8"))
        rev = next(b["revision"] for b in data["browsers"] if b["name"] == "chromium")
        base = Path(os.getenv("LOCALAPPDATA", "")) / "ms-playwright"
        have = sorted(d.name for d in base.glob("chromium-*")) if base.is_dir() else []
        ok = any(f"chromium-{rev}" == h for h in have)
        if not ok:
            print(f"  ⚠️ 内核版本不匹配: patchright 期望 chromium-{rev}, 本机只有 {have or '无'}")
            print("     请先运行: uv run python -m patchright install chromium, 再重新打包")
        else:
            print(f"  内核版本一致: chromium-{rev}")
        return ok
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️ 内核版本校验跳过: {e}")
        return True


if __name__ == "__main__":
    if not verify_kernel_revision():
        raise SystemExit("内核版本不匹配, 已中止打包。请先安装匹配版本的内核。")
    z = build_colleague()
    print(f"built {z.name} ({z.stat().st_size} bytes)")
    ok = verify_contains(
        z,
        ["mpau_cli.py", "pyproject.toml",
         "pipeline/store.py", "pipeline/copy_engine.py", "pipeline/scheduler.py",
         "pipeline/batch_runner.py", "pipeline/data/copy_rules.json",
         "web/app.py", "web/templates/index.html", "web/README.md",
         "tests/test_batch_flow.py"],
    )
    with zipfile.ZipFile(z) as zf:
        has_chromium = any(n.startswith("ms-playwright/chromium-") for n in zf.namelist())
    if not has_chromium:
        print(f"  ⚠️ {z.name} 缺少浏览器内核(ms-playwright/chromium-*)")
    print("checks:", "PASS" if (ok and has_chromium) else "FAIL")
