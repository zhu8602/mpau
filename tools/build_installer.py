# -*- coding: utf-8 -*-
"""构建 mpau 安装版: staging 便携目录 → Inno Setup 编译 setup.exe。

staging 布局:
  app/                项目源码(含 web/ui/dist, 不含 data/cookies/logs 等运行数据)
  python/             完整可搬 CPython(依赖已预装到其 site-packages)
  kernels/ms-playwright/  patchright 浏览器内核(安装时释放到目标机 %LOCALAPPDATA%/ms-playwright)
  mpau-launcher.exe   启动器(tools/launcher.py 经 PyInstaller 冻结)

用法:
  uv run python tools/build_installer.py               # 完整构建(缺 Inno 时自动下载便携版)
  uv run python tools/build_installer.py --no-inno     # 只产 staging 便携目录
  uv run python tools/build_installer.py --skip-kernels --skip-pip   # 快速迭代(复用已有依赖/内核)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "package" / "build"
STAGE = BUILD / "staging"
DIST = ROOT / "package" / "dist"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
INNO_DIR = BUILD / "inno"
ISCC = INNO_DIR / "ISCC.exe"
# Inno 官方下载已于 2026-03 迁移到 GitHub Releases; 国内构建可用 MPAU_INNO_URL 指定镜像
INNO_URL = os.environ.get(
    "MPAU_INNO_URL",
    "https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe",
)
INNO_ISL_URL = os.environ.get(
    "MPAU_INNO_ISL_URL",
    "https://raw.githubusercontent.com/jrsoftware/issrc/refs/heads/main/Files/Languages/ChineseSimplified.isl",
)
TSINGHUA = "https://pypi.tuna.tsinghua.edu.cn/simple"

# 运行所需的源码/资源(白名单), 其余(测试/工具/文档/设计稿)不进安装包
APP_INCLUDE = [
    "mpau_cli.py", "pyproject.toml",
    "uploader", "utils", "pipeline",
    "web/app.py", "web/tray.py", "web/templates", "web/ui/dist", "web/README.md",
    "docs/使用手册.html",
    "assets/icon.png",
    "LICENSE",
]
KERNEL_SHARED = ("ffmpeg-", "winldd-")  # 内核公共组件前缀


def run(cmd: list[str], **kw) -> None:
    print(f"$ {' '.join(str(c) for c in cmd)[:140]}", flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def project_deps() -> list[str]:
    import tomllib
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return list(data["project"]["dependencies"]) + list(data["project"]["optional-dependencies"]["web"])


def project_version() -> str:
    """版本号唯一来源: pyproject.toml(installer.iss 的默认值仅作兜底)。"""
    import tomllib
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def stage_python(skip_pip: bool) -> None:
    """复制构建机的 CPython(uv 管理的完整安装, 可搬迁)并预装依赖。"""
    dst = STAGE / "python"
    if dst.exists() and skip_pip:
        print("== python 复用已有 staging")
        return
    src = Path(sys.base_prefix)
    py = dst / "python.exe"
    if not py.is_file():
        print(f"== 拷贝 Python: {src}")
        shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "test", "tests"))
        # uv 管理的 CPython 带 PEP 668 标记(externally-managed), 会拒绝 ensurepip/pip; 副本里删掉即可, 不动源安装
        marker = dst / "Lib" / "EXTERNALLY-MANAGED"
        if marker.exists():
            marker.unlink()
        run([py, "-m", "ensurepip", "--upgrade"])
    else:
        print("== Python 已存在, 跳过拷贝")
    if not skip_pip:
        index = os.environ.get("PIP_INDEX_URL", TSINGHUA)
        run([py, "-m", "pip", "install", "--no-warn-script-location", "--disable-pip-version-check",
             "-i", index, *project_deps()])
        # 依赖已移除的包不会随 install 自动消失, 显式清掉旧 staging 残留(如 playwright)
        if not any(d.split("=")[0].split(">")[0].strip() == "playwright" for d in project_deps()):
            subprocess.run([str(py), "-m", "pip", "uninstall", "-y", "playwright"],
                           check=False, capture_output=True)


def stage_app() -> None:
    dst = STAGE / "app"
    print("== 拷贝项目源码")
    if dst.exists():
        # 整目录重建: dirs_exist_ok 的增量拷贝会把已删除的死文件一直带进安装包
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for item in APP_INCLUDE:
        src = ROOT / item
        target = dst / item
        if src.is_dir():
            # 注意: 不能排除 "data" —— pipeline/data/copy_rules.json 是必须随包发布的规则数据;
            # 根级运行数据(data/ cookies/ logs/)本来就不在 APP_INCLUDE 白名单里, 不会被拷
            shutil.copytree(src, target, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "node_modules"))
        elif src.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        else:
            print(f"  ⚠️ 缺失: {item}")


def _expected_revisions(pkg: str) -> set[str]:
    browsers_json = ROOT / ".venv" / "Lib" / "site-packages" / pkg / "driver" / "package" / "browsers.json"
    if not browsers_json.is_file():
        return set()
    data = json.loads(browsers_json.read_text(encoding="utf-8"))
    # firefox/webkit 无活代码引用(TikTok/百家号走 chromium),不收进安装包
    return {
        f"{b['name'].replace('-', '_')}-{b['revision']}"
        for b in data["browsers"]
        if b.get("installByDefault") and b["name"] not in ("firefox", "webkit")
    }


def stage_kernels(skip: bool) -> None:
    dst = STAGE / "kernels" / "ms-playwright"
    if dst.exists() and skip:
        print("== 内核复用已有 staging")
        return
    # patchright 内核(全平台上传器 + UI 窗口共用)若缺失先在构建机下载
    missing = [r for r in _expected_revisions("patchright")
               if not (Path(os.environ["LOCALAPPDATA"]) / "ms-playwright" / r).is_dir()]
    if missing:
        print(f"== 构建机补装 patchright 内核: {sorted(missing)}")
        run([VENV_PY, "-m", "patchright", "install", "chromium"])
    keep = _expected_revisions("patchright")
    base = Path(os.environ["LOCALAPPDATA"]) / "ms-playwright"
    print(f"== 拷贝浏览器内核 -> {dst}")
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for d in sorted(base.iterdir()):
        if d.is_dir() and (d.name in keep or d.name.startswith(KERNEL_SHARED)):
            print(f"  + {d.name}")
            shutil.copytree(d, dst / d.name)


def stage_launcher() -> None:
    print("== 冻结启动器 mpau-launcher.exe")
    icon = ROOT / "assets" / "icon.ico"
    cmd = [VENV_PY, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--noconsole",
           "--name", "mpau-launcher", "--distpath", str(STAGE),
           "--workpath", str(BUILD / "pyi"), "--specpath", str(BUILD / "pyi")]
    if icon.is_file():
        cmd += ["--icon", str(icon)]
    run([*cmd, str(ROOT / "tools" / "launcher.py")])


def ensure_inno() -> Path | None:
    """定位 ISCC; 缺失时下载官方安装包并以便携模式解包到 package/build/inno。"""
    if not ISCC.is_file():
        candidates = [os.environ.get("MPAU_ISCC", ""), r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"]
        for c in candidates:
            if c and Path(c).is_file():
                return Path(c)
        print(f"== 下载便携 Inno Setup: {INNO_URL}")
        INNO_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as td:
            installer = Path(td) / "inno.exe"
            urllib.request.urlretrieve(INNO_URL, installer)
            # /PORTABLE=1 免管理员解包, 不写注册表
            run([installer, "/VERYSILENT", "/SP-", "/PORTABLE=1", f"/DIR={INNO_DIR}"])
    # 官方便携版不含简体中文语言文件, 缺失时补齐(installer.iss 的 [Languages] 依赖它)
    isl = INNO_DIR / "Languages" / "ChineseSimplified.isl"
    if ISCC.is_file() and not isl.is_file():
        print("== 补齐 Inno 简体中文语言文件")
        urllib.request.urlretrieve(INNO_ISL_URL, isl)
    return ISCC if ISCC.is_file() else None


def compile_installer() -> Path | None:
    iscc = ensure_inno()
    if not iscc:
        print("⚠️ 未找到 Inno Setup, 跳过 setup.exe 编译(只产出 staging)")
        return None
    DIST.mkdir(parents=True, exist_ok=True)
    version = project_version()
    print(f"== 编译安装包 (版本 {version})")
    run([iscc, "/Q", f"/DMyAppVersion={version}", str(ROOT / "tools" / "installer.iss")])
    outs = sorted(DIST.glob(f"mpau-setup-{version}.exe"))
    return outs[-1] if outs else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-inno", action="store_true", help="只产 staging, 不编译 setup.exe")
    ap.add_argument("--skip-pip", action="store_true", help="复用 staging 里已装好的依赖")
    ap.add_argument("--skip-kernels", action="store_true", help="复用 staging 里已拷好的内核")
    ap.add_argument("--skip-preflight", action="store_true", help="跳过打包前自检(不建议)")
    args = ap.parse_args()

    print(f"== 目标版本: {project_version()}")
    if not args.skip_preflight:
        # 拦下"漏构建前端 / 版本号不一致 / 文档过期 / 缺依赖内核"这几类返工
        # 以脚本方式运行时 sys.path[0] 是 tools/, 需显式把仓库根加进来才能 import tools.*
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from tools.preflight import run_checks
        failures = run_checks()
        if failures:
            for f in failures:
                print(f"  ❌ {f}")
            raise SystemExit("打包前自检未通过, 已中止(如确认无碍可加 --skip-preflight)")
        print("  preflight OK")

    STAGE.mkdir(parents=True, exist_ok=True)
    stage_python(args.skip_pip)
    stage_app()
    stage_kernels(args.skip_kernels)
    stage_launcher()

    print("== staging 自检")
    checks = [
        STAGE / "python" / "python.exe",
        STAGE / "app" / "web" / "app.py",
        STAGE / "app" / "mpau_cli.py",
        STAGE / "app" / "web" / "ui" / "dist" / "index.html",
        STAGE / "mpau-launcher.exe",
    ]
    bad = [str(p) for p in checks if not p.is_file()]
    if bad:
        raise SystemExit(f"staging 缺文件: {bad}")
    if not list((STAGE / "kernels" / "ms-playwright").glob("chromium-*")):
        raise SystemExit("staging 缺浏览器内核")
    print("  staging OK")

    if args.no_inno:
        print(f"完成(未编译安装包): {STAGE}")
        return 0
    out = compile_installer()
    if out:
        print(f"安装包: {out} ({out.stat().st_size / 1024 / 1024:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
