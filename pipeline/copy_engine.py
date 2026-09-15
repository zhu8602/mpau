# -*- coding: utf-8 -*-
"""AI 文案引擎: 一条人工标题 → 各平台差异化标题/描述/标签。

- LLM 走 OpenAI 兼容接口(requests), provider 通过 data/config.json 配置
- 每平台一次调用, 并发执行, 每次返回 2~3 个候选
- 候选经 pipeline.rules 校验(字数硬性、违禁词提示), 不合规候选剔除
- model == "mock" 时返回确定性占位候选(测试/无 Key 演示用)
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

from pipeline import rules
from pipeline.config import DEFAULT_CONFIG, get_llm_config

MOCK_MODEL = "mock"

GOODS_TITLE_MAX = 10  # 商品短标题最大字数

SYSTEM_PROMPT = (
    "你是资深电商短视频运营, 精通抖音/快手/视频号/小红书的内容风格差异。"
    "你只根据用户提供的标题、描述、标签、商品信息来扩写, 严禁编造视频中不存在的卖点。"
    "输出必须是合法 JSON, 不要输出任何解释文字。"
)


def _json_schema_for(platform: str) -> str:
    fields = (
        '{"title": "标题(必填)", "desc": "描述(可为空字符串)", "tags": ["标签1", "标签2"]}'
    )
    if platform == "tencent":
        fields = (
            '{"title": "正文第一行, 即标题", "short_title": "≤16字短标题", '
            '"desc": "正文后续内容, 文末带#话题", "tags": ["话题1", "话题2"]}'
        )
    elif platform == "pdd":
        fields = '{"title": "", "desc": "描述(必填)", "tags": ["标签1", "标签2"]}'
    return (
        '{"candidates": [' + fields + ", " + fields + ", " + fields + "]}"
    )


def build_messages(platform: str, base: dict[str, Any], avoid_titles: list[str] | None = None) -> list[dict]:
    rule = rules.rule_for(platform)
    goods = base.get("goods") or {}
    goods_line = ""
    if platform == "douyin" and (goods.get("link") or goods.get("title")):
        goods_line = (
            f"商品链接: {goods.get('link', '')}\n商品短标题: {goods.get('title', '')}\n"
            "文案要自然带出商品卖点。\n"
        )
    elif rule.get("goods") == "goods_id" and goods.get("id"):
        goods_line = f"挂载商品ID: {goods.get('id')}\n文案要自然带出商品卖点。\n"

    tags_line = ""
    if base.get("tags"):
        tags_line = "参考标签: " + ", ".join(rules.clean_tags(base["tags"])) + "\n"

    desc_line = ""
    if base.get("desc"):
        desc_line = f"补充信息: {base['desc']}\n"

    title = str(base.get("title") or "").strip()
    title_line = f"人工标题: {title}" if title else "人工标题: (无, 请根据运营要求自行起标题)"
    brief_line = ""
    brief = str(base.get("brief") or "").strip()
    if brief:
        brief_line = f"运营要求: {brief}\n"

    avoid_line = ""
    avoid = [str(t).strip() for t in (avoid_titles or []) if str(t).strip()]
    if avoid:
        avoid_line = "本批次已使用标题(严禁重复或高度相似):\n" + "\n".join(f"- {t}" for t in avoid) + "\n"

    user_prompt = f"""为「{rule['cn']}」平台改写下面这条视频的发布文案, 生成 {3} 个风格不同的候选。

{title_line}
{brief_line}{desc_line}{tags_line}{goods_line}{avoid_line}
平台要求:
- 标题风格: {rule['title_style']}
- 描述风格: {rule['desc_style']}
- 标签风格: {rule['tag_style']}
- 硬性限制: 标题最多 {rule.get('title_max')} 字; 避免使用这些词: {', '.join(rule.get('banned') or [])}
- 其他说明: {rule.get('notes', '')}
- 以上平台硬性限制(字数/违禁词)优先于「运营要求」, 冲突时以平台限制为准。

{json_schema_instruction(platform)}"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def json_schema_instruction(platform: str) -> str:
    return (
        "只返回 JSON, 结构如下(不要 markdown 代码块):\n"
        + _json_schema_for(platform)
    )


def _first_balanced_json_object(text: str, start: int) -> str:
    """从 start 处的 { 开始括号配对(支持嵌套/字符串/转义), 返回第一个完整 JSON 对象子串。"""
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return ""


def _extract_json(text: str) -> Any:
    """宽松解析 LLM 返回: 剥代码块 → 整体解析 → 取首个完整 JSON 对象 → 修复尾逗号。"""
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    candidates = [text]
    start = text.find("{")
    if start != -1:
        balanced = _first_balanced_json_object(text, start)
        if balanced:
            candidates.append(balanced)
    last_err: Exception | None = None
    for cand in candidates:
        for attempt in (cand, re.sub(r",\s*([}\]])", r"\1", cand)):
            try:
                return json.loads(attempt)
            except ValueError as exc:
                last_err = exc
    snippet = " ".join(text.split())[:150]
    raise ValueError(f"返回内容不是合法 JSON ({last_err}): {snippet}")


def _call_llm(messages: list[dict], cfg: dict[str, Any], temperature: float | None = None) -> str:
    if cfg.get("model") == MOCK_MODEL or cfg.get("base_url") == MOCK_MODEL:
        return _mock_response(messages)
    api_key = (cfg.get("api_key") or "").strip()
    if not api_key:
        raise RuntimeError("未配置 LLM API Key, 请先在设置页配置")
    base_url = (cfg.get("base_url") or "").rstrip("/")
    if not base_url:
        raise RuntimeError("未配置 LLM 接口地址")
    url = base_url + "/chat/completions"
    payload: dict[str, Any] = {
        "model": cfg.get("model") or "deepseek-chat",
        "messages": messages,
        "max_tokens": int(cfg.get("max_tokens", 2048)),
        "temperature": temperature if temperature is not None else float(cfg.get("temperature", 1.0)),
        "response_format": {"type": "json_object"},
    }

    def _post(body: dict[str, Any]):
        try:
            return requests.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body,
                timeout=int(cfg.get("timeout", 60)),
            )
        except requests.exceptions.Timeout:
            raise RuntimeError("LLM 请求超时, 请重试或检查网络") from None
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(f"LLM 请求失败: {exc}") from None

    resp = _post(payload)
    # 部分兼容端点不支持 response_format=json_object → 去掉后自动重试一次
    if resp.status_code == 400 and "response_format" in (resp.text or ""):
        payload = {k: v for k, v in payload.items() if k != "response_format"}
        resp = _post(payload)
    if resp.status_code != 200:
        detail = (resp.text or "")[:200]
        raise RuntimeError(f"LLM 接口错误 HTTP {resp.status_code}: {detail}")
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"LLM 返回格式异常: {str(data)[:200]}") from exc


def _mock_response(messages: list[dict]) -> str:
    """无 Key 演示/测试用: 从 user prompt 中取出人工标题(无则用运营要求里的卖点), 生成确定性候选。
    模拟 LLM 遵守去重要求: 已使用标题对应的候选会被跳过。"""
    user = messages[-1]["content"] if messages else ""
    m = re.search(r"人工标题:\s*(.+)", user)
    base = m.group(1).strip() if m else ""
    if base.startswith("(无") or base.startswith("（无"):
        base = ""  # 占位说明, 不是真实标题
    if not base:
        m = re.search(r"运营要求:\s*(.+)", user)
        base = (m.group(1).strip() if m else "新品实测")[:40]
        mm = re.search(r"卖点[:：]\s*([^\n,，。;；]{2,40})", base)
        if mm:
            base = mm.group(1).strip()[:40]
    avoid: set[str] = set()
    m2 = re.search(r"本批次已使用标题.*?\n((?:- .*\n?)*)", user)
    if m2:
        avoid = {ln[2:].strip() for ln in m2.group(1).splitlines() if ln.startswith("- ")}
    variants = ["实测分享", "真心推荐", "用了就懂"]
    candidates = []
    for v in variants:
        title = f"{base[:30]}｜{v}"
        if title in avoid and len(candidates) < len(variants) - 1:
            continue  # 已用过的不再重复生成
        candidates.append(
            {"title": title, "desc": f"{base} {v}", "tags": ["好物", "测评"]}
        )
    if not candidates:  # 全部被避让时兜底
        candidates.append(
            {"title": f"{base[:30]}｜{variants[0]}", "desc": f"{base} {variants[0]}", "tags": ["好物", "测评"]}
        )
    return json.dumps({"candidates": candidates}, ensure_ascii=False)


def _pick_candidates(platform: str, payload: Any, n: int) -> tuple[list[dict], str]:
    """从 LLM 返回里取候选并逐条校验; 返回 (合格候选, 错误信息)。"""
    cands = payload.get("candidates") if isinstance(payload, dict) else None
    if not isinstance(cands, list) or not cands:
        return [], "LLM 未返回 candidates 列表"
    accepted: list[dict] = []
    warned_any = False
    for raw in cands:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        if not title and not raw.get("desc"):
            continue
        if not title and str(raw.get("desc") or "").strip():
            # PDD 等无标题平台: 描述即内容
            pass
        cand = {
            "title": title,
            "desc": str(raw.get("desc") or "").strip(),
            "tags": rules.clean_tags(raw.get("tags")),
            "short_title": str(raw.get("short_title") or "").strip(),
            "issues": [],
        }
        issues = rules.validate_candidate(platform, cand)
        hard = [i for i in issues if i["level"] == "error"]
        if hard:
            continue
        if issues:
            warned_any = True
        cand["issues"] = issues
        accepted.append(cand)
        if len(accepted) >= n:
            break
    if not accepted:
        return [], "生成结果均不符合平台字数要求(如超长), 请调整人工标题或重试"
    if len(accepted) < 2:
        pass
    return accepted, ("部分候选含违禁词提示, 建议人工确认" if warned_any else "")


def generate_one(
    platform: str,
    base: dict[str, Any],
    cfg: dict[str, Any] | None = None,
    n: int | None = None,
    with_desc: bool = True,
    with_tags: bool = True,
    avoid_titles: list[str] | None = None,
) -> dict:
    """单平台生成。返回 {platform, cn, candidates, error?}。
    JSON 解析失败时自动降温度重试一次, 仍失败则报错并附返回片段。
    avoid_titles: 本批次已使用标题, 提示 LLM 避免重复。"""
    cfg = cfg or get_llm_config()
    n = n or int(cfg.get("n_candidates", DEFAULT_CONFIG["llm"]["n_candidates"]))
    messages = build_messages(platform, base, avoid_titles)

    def _fail(msg: str) -> dict:
        return {"platform": platform, "cn": rules.platform_cn(platform), "candidates": [], "error": msg}

    try:
        text = _call_llm(messages, cfg)
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))

    try:
        payload = _extract_json(text)
    except ValueError as exc:
        # 解析失败: 降温度自动重试一次
        try:
            payload = _extract_json(_call_llm(messages, cfg, temperature=0.5))
        except Exception as exc2:  # noqa: BLE001
            snippet = " ".join((text or "").split())[:150]
            return _fail(f"{exc2} (已自动重试一次); 首次返回片段: {snippet}")

    try:
        cands, warn = _pick_candidates(platform, payload, n)
        if not with_desc:
            for c in cands:
                c["desc"] = ""
        if not with_tags:
            for c in cands:
                c["tags"] = []
        result: dict[str, Any] = {
            "platform": platform,
            "cn": rules.platform_cn(platform),
            "candidates": cands,
        }
        if warn:
            result["warning"] = warn
        return result
    except Exception as exc:  # noqa: BLE001
        return _fail(str(exc))


def generate_copy(
    platforms: list[str],
    base: dict[str, Any],
    cfg: dict[str, Any] | None = None,
    n: int | None = None,
    with_desc: bool = True,
    with_tags: bool = True,
    max_workers: int = 4,
    avoid_titles: list[str] | None = None,
) -> dict[str, Any]:
    """并发生成多个平台。返回 {platform: {cn, candidates, error?}}。"""
    cfg = cfg or get_llm_config()
    n = n or int(cfg.get("n_candidates", DEFAULT_CONFIG["llm"]["n_candidates"]))
    if not base.get("title") and not str(base.get("brief") or "").strip():
        return {"error": "人工标题与 AI 提示词均为空, 无法生成"}
    results: dict[str, Any] = {}
    if len(platforms) <= 1:
        for p in platforms:
            results[p] = generate_one(p, base, cfg, n, with_desc, with_tags, avoid_titles)
        return results
    with ThreadPoolExecutor(max_workers=min(max_workers, len(platforms))) as pool:
        futures = {
            p: pool.submit(generate_one, p, base, cfg, n, with_desc, with_tags, avoid_titles)
            for p in platforms
        }
        for p, fut in futures.items():
            results[p] = fut.result()
    return results


# ---------------------------------------------------------------------------
# 商品短标题(货架标题): 根据批次 AI 提示词(关键词/卖点)+人工标题推断
# ---------------------------------------------------------------------------
def _build_goods_title_messages(base: dict[str, Any], avoid: set[str]) -> list[dict]:
    title = str(base.get("title") or "").strip()
    title_line = f"人工标题: {title}" if title else "人工标题: (无)"
    brief = str(base.get("brief") or "").strip()
    brief_line = f"关键词/卖点(运营要求): {brief}\n" if brief else ""
    avoid_line = ""
    if avoid:
        avoid_line = "本批次已使用短标题(严禁重复或高度相似):\n" + "\n".join(f"- {t}" for t in sorted(avoid)) + "\n"

    user_prompt = f"""根据下面信息推断商品的货架短标题, 生成 3 个风格不同的候选。

{title_line}
{brief_line}{avoid_line}
要求:
- 每个短标题不超过 {GOODS_TITLE_MAX} 个字, 突出核心卖点, 适合电商货架展示
- 不要 emoji, 不要标点堆砌, 不要使用夸大违禁词(最/第一/全网等)

只返回 JSON, 结构如下(不要 markdown 代码块):
{{"titles": ["短标题1", "短标题2", "短标题3"]}}"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


def _mock_goods_title(base: dict[str, Any], avoid: set[str]) -> dict[str, Any]:
    """mock 模式: 人工标题优先、其次 brief 卖点作为种子, 生成确定性短标题并避让已用。"""
    seed = str(base.get("title") or "").strip()
    if not seed:
        brief = str(base.get("brief") or "").strip()
        m = re.search(r"卖点[:：]\s*([^\n,，。;；]{2,20})", brief)
        seed = (m.group(1).strip() if m else brief) or "新品"
    seed = seed[:6]
    variants = [f"{seed}优选", f"{seed}好物", f"{seed}特惠"]
    titles = []
    for v in variants:
        v = v[:GOODS_TITLE_MAX]
        if v in avoid and len(titles) < len(variants) - 1:
            continue  # 已用过的不再重复生成
        titles.append(v)
    if not titles:  # 全部被避让时兜底
        titles = [variants[0][:GOODS_TITLE_MAX]]
    chosen = next((t for t in titles if t not in avoid), titles[0])
    return {"title": chosen}


def generate_goods_title(
    base: dict[str, Any],
    cfg: dict[str, Any] | None = None,
    avoid: list[str] | None = None,
) -> dict[str, Any]:
    """推断商品短标题(≤GOODS_TITLE_MAX 字)。返回 {"title": str} 或 {"error": msg}。

    base: 与 generate_one 同构(title/brief/goods 等); 关键词主要来自 brief。
    avoid: 本批次已使用短标题, 保证批内多样性。JSON 解析失败自动降温度重试一次。
    """
    cfg = cfg or get_llm_config()
    avoid_set = {str(t).strip() for t in (avoid or []) if str(t).strip()}
    if cfg.get("model") == MOCK_MODEL or cfg.get("base_url") == MOCK_MODEL:
        return _mock_goods_title(base, avoid_set)
    if not str(base.get("title") or "").strip() and not str(base.get("brief") or "").strip():
        return {"error": "人工标题与 AI 提示词均为空, 无法推断商品短标题"}
    messages = _build_goods_title_messages(base, avoid_set)

    try:
        text = _call_llm(messages, cfg)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}

    try:
        payload = _extract_json(text)
    except ValueError as exc:
        try:
            payload = _extract_json(_call_llm(messages, cfg, temperature=0.5))
        except Exception as exc2:  # noqa: BLE001
            snippet = " ".join((text or "").split())[:150]
            return {"error": f"{exc2} (已自动重试一次); 首次返回片段: {snippet}"}

    titles = payload.get("titles") if isinstance(payload, dict) else None
    if not isinstance(titles, list) or not titles:
        return {"error": "LLM 未返回 titles 列表"}
    cleaned: list[str] = []
    for raw in titles:
        t = str(raw or "").strip().strip("# ")
        if t and len(t) <= GOODS_TITLE_MAX and t not in cleaned:
            cleaned.append(t)
    if not cleaned:
        return {"error": f"生成的短标题均为空或超过 {GOODS_TITLE_MAX} 字, 请调整关键词后重试"}
    chosen = next((t for t in cleaned if t not in avoid_set), cleaned[0])
    return {"title": chosen}
