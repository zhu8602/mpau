# -*- coding: utf-8 -*-
"""打包前自检: 拦住最容易返工的四类问题。

1. 版本号一致性      pyproject.toml 与 tools/installer.iss 的默认值必须相同
2. 前端新鲜度        web/ui/dist 必须比 web/ui/src 新(否则装出来的还是旧界面)
3. 文档一致性        随包发布的使用手册不得残留"全局串行"等与实现不符的说法
4. 白名单与内核      APP_INCLUDE 每项存在; patchright 期望的内核已在构建机就位

用法:
  python tools/preflight.py           # 打印每项结果, 有失败则退出码 1
  python tools/preflight.py --json    # 机器可读输出
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# 1) 版本号一致性
# --------------------------------------------------------------------------
def check_version() -> tuple[bool, str]:
    import tomllib

    py = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = str(py["project"]["version"])
    iss = (ROOT / "tools" / "installer.iss").read_text(encoding="utf-8")
    m = re.search(r'#define\s+MyAppVersion\s+"([^"]+)"', iss)
    if not m:
        return False, "installer.iss 里找不到 MyAppVersion 定义"
    iss_version = m.group(1)
    if version != iss_version:
        return False, (f"版本号不一致: pyproject.toml={version} / "
                       f"installer.iss 默认值={iss_version}")
    return True, f"版本号一致: {version}"


# --------------------------------------------------------------------------
# 2) 前端新鲜度
# --------------------------------------------------------------------------
def check_frontend() -> tuple[bool, str]:
    dist = ROOT / "web" / "ui" / "dist"
    src = ROOT / "web" / "ui" / "src"
    public = ROOT / "web" / "ui" / "public"
    index = dist / "index.html"
    if not index.is_file():
        return False, f"前端产物缺失: {index}(请先 cd web/ui && pnpm build)"
    if not src.is_dir():
        return True, "未找到 web/ui/src, 跳过新鲜度检查"
    src_latest = max((p.stat().st_mtime for p in src.rglob("*") if p.is_file()), default=0.0)
    # 只比"构建产物": dist/assets/* + index.html。
    # dist 根下还有 public/ 原样拷贝的静态文件(如 icons.svg), 它们不由 vite 生成, 比源码旧属正常。
    built = [p for p in (dist / "assets").rglob("*") if p.is_file()] if (dist / "assets").is_dir() else []
    built.append(index)
    if not built:
        return False, f"前端产物为空: {dist / 'assets'}"
    stale = [p for p in built if p.stat().st_mtime < src_latest]
    if stale:
        import datetime as _dt
        names = ", ".join(sorted(p.name for p in stale)[:3])
        return False, (
            f"前端产物比源码旧(src 最新 {_dt.datetime.fromtimestamp(src_latest):%Y-%m-%d %H:%M:%S}, "
            f"过期产物: {names}), 请重新 pnpm build"
        )
    # public/ 里被改过但没重新 build 的话, dist 下的副本会落后
    if public.is_dir():
        behind = []
        for p in public.rglob("*"):
            if not p.is_file():
                continue
            cp = dist / p.relative_to(public)
            if cp.is_file() and cp.stat().st_mtime < p.stat().st_mtime:
                behind.append(p.name)
        if behind:
            return False, f"public/ 下已更新但未重新构建: {sorted(behind)}(请 pnpm build)"
    return True, f"前端产物新鲜({len(built)} 个构建产物)"


# --------------------------------------------------------------------------
# 3) 文档一致性(轻量断言: 只查会被用户当真的硬说法)
# --------------------------------------------------------------------------
# 已废弃的说法 -> 说明(2026-09-11: 调度器是跨「平台+账号」并发, 非全局串行)
FORBIDDEN_MANUAL = [
    ("全局串行", "调度器为跨平台账号并发(默认 4), 不是全局串行"),
    # 系统没有内置对话界面: skills/ 是给外部 AI Agent 读的 SKILL.md 协议, 且不随安装包发布
    ("对话式发布", "系统不含对话界面; 智能体能力是外部 Agent 读 skills/*/SKILL.md 后调 CLI"),
]
# 必须出现的关键说法 -> 说明(缺失说明文案又漂移了)
REQUIRED_MANUAL = [
    ("LLM API Key", "必须提醒: 用 AI 生成文案前要配置 LLM Key(copy_engine 无 Key 直接报错)"),
    ("mpau-data", "必须写明安装版数据目录 %LOCALAPPDATA%\\mpau-data"),
    ("exe", "快速开始必须给出「双击 exe 即用」的安装版路径"),
]
MANUAL_MAX_KB = 600       # 体积看门狗: 手册内嵌了一张工作台实景图(base64 ~270KB), 总量应 ~310KB; 误塞多张大图会报警
MANUAL_STEP_COUNT = 7     # 快速开始步骤数(加了「配置 AI 文案引擎」与「导入素材」, 5→7)


def check_manual() -> tuple[bool, str]:
    manual = ROOT / "docs" / "使用手册.html"
    if not manual.is_file():
        return False, f"使用手册缺失: {manual}(会随安装包发布)"
    size_kb = manual.stat().st_size / 1024
    if size_kb > MANUAL_MAX_KB:
        return False, f"使用手册体积 {size_kb:.0f}KB 超过阈值 {MANUAL_MAX_KB}KB(误塞大图?)"
    text = manual.read_text(encoding="utf-8", errors="replace")
    bad = [f"「{kw}」({why})" for kw, why in FORBIDDEN_MANUAL if kw in text]
    if bad:
        return False, "使用手册残留与实现不符的说法: " + "; ".join(bad)
    missing = [f"{kw}({why})" for kw, why in REQUIRED_MANUAL if kw not in text]
    if missing:
        return False, "使用手册缺少必要说明: " + "; ".join(missing)
    # HTML 结构平衡(手工编辑最容易破坏; 上次就误删过一个 </div> 换行)
    for tag in ("div", "tr", "table", "details"):
        o = len(re.findall(rf"<{tag}\b", text))
        c = len(re.findall(rf"</{tag}>", text))
        if o != c:
            return False, f"使用手册 HTML 不平衡: <{tag}>={o} 但 </{tag}>={c}"
    # 快速开始步骤数
    steps = len(re.findall(r'class="step"', text))
    if steps != MANUAL_STEP_COUNT:
        return False, f"使用手册快速开始步骤数={steps}, 期望 {MANUAL_STEP_COUNT}"
    # 快手已支持挂车(按商品名称): 平台表里该行的「挂商品」单元格不应还是 "—"
    row = re.search(r"<tr><td>快手[^<]*</td>(.*?)</tr>", text, re.S)
    if not row:
        return False, "使用手册里找不到快手所在的能力表行"
    cells = re.findall(r"<td[^>]*>(.*?)</td>", row.group(1), re.S)
    # 列序: 类别 视频 图文 定时 挂商品 试跑 标题限制 → 挂商品是第 5 个
    if len(cells) < 5:
        return False, f"使用手册快手行单元格数异常({len(cells)})"
    goods_cell = re.sub(r"<[^>]+>", "", cells[4]).strip()
    if goods_cell in ("", "—", "-"):
        return False, f"使用手册平台表: 快手「挂商品」仍标为 {goods_cell!r}, 实际已支持(按商品名称)"
    return True, (f"使用手册一致({size_kb:.0f}KB, {steps} 步, "
                  f"快手挂商品={goods_cell})")


# --------------------------------------------------------------------------
# 4) 白名单与浏览器内核
# --------------------------------------------------------------------------
def check_include_list() -> tuple[bool, str]:
    sys.path.insert(0, str(ROOT))
    from tools.build_installer import APP_INCLUDE  # noqa: PLC0415

    missing = [item for item in APP_INCLUDE if not (ROOT / item).exists()]
    if missing:
        return False, f"APP_INCLUDE 里有不存在的项: {missing}"
    # 历史踩坑: copytree 排除 data 会漏掉随包必需的规则文件
    rules = ROOT / "pipeline" / "data" / "copy_rules.json"
    if not rules.is_file():
        return False, f"规则数据缺失: {rules}"
    return True, f"白名单 {len(APP_INCLUDE)} 项齐全"


def check_kernels() -> tuple[bool, str]:
    sys.path.insert(0, str(ROOT))
    from tools.build_installer import _expected_revisions  # noqa: PLC0415

    expected = _expected_revisions("patchright")
    if not expected:
        return False, "读不到 patchright 的 browsers.json(构建机依赖不完整?)"
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    if not local.is_dir():
        return False, f"浏览器内核目录不存在: {local}"
    have = {d.name for d in local.iterdir() if d.is_dir()}
    missing = sorted(r for r in expected if r not in have)
    if missing:
        return False, f"构建机缺 patchright 内核: {missing}(先 python -m patchright install chromium)"
    return True, f"内核就位: {sorted(expected)}"


# --------------------------------------------------------------------------
# 运行中的服务会不会占用内核/产物(Windows 下拷贝被占用文件会失败)
# --------------------------------------------------------------------------
def check_running_service() -> tuple[bool, str]:
    try:
        import subprocess
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-NetTCPConnection -LocalPort 8898 -State Listen -ErrorAction SilentlyContinue | "
             "Measure-Object).Count"],
            capture_output=True, text=True, timeout=20,
        ).stdout.strip()
        if out and out != "0":
            return True, "提示: 8898 有服务在跑(打包可继续, 但若它占用内核文件, 拷内核会失败)"
        return True, "8898 空闲"
    except Exception:  # noqa: BLE001
        return True, "跳过运行中服务检查"


CHECKS = [
    ("版本号一致性", check_version),
    ("前端新鲜度", check_frontend),
    ("使用手册一致性", check_manual),
    ("打包白名单", check_include_list),
    ("浏览器内核", check_kernels),
    ("运行环境提示", check_running_service),
]


def run_checks(verbose: bool = True) -> list[str]:
    """返回失败说明列表(空列表 = 全部通过)。供 build_installer 调用。"""
    failures: list[str] = []
    for name, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, f"检查抛异常: {exc}"
        if verbose:
            print(f"  [{'OK' if ok else 'FAIL'}] {name}: {detail}")
        if not ok:
            failures.append(f"{name}: {detail}")
    return failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.json:
        results = []
        for name, fn in CHECKS:
            try:
                ok, detail = fn()
            except Exception as exc:  # noqa: BLE001
                ok, detail = False, f"检查抛异常: {exc}"
            results.append({"check": name, "ok": ok, "detail": detail})
        print(json.dumps({"ok": all(r["ok"] for r in results), "results": results},
                         ensure_ascii=False, indent=2))
    failures = run_checks(verbose=not args.json)
    if failures:
        print(f"\n❌ 自检未通过({len(failures)} 项)")
        return 1
    print("\n✅ 自检全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
