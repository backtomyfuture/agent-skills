#!/usr/bin/env python3
"""Build a Paid AI Inference Index from OpenRouter public data."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


RANKINGS_URL = "https://openrouter.ai/rankings?view=week"
MODELS_URL = "https://openrouter.ai/api/v1/models"
MODEL_RANKINGS_ACTION_ID = "40824635c5eb77626bdf6795ffbf382c0862b321e1"
MODEL_RANKINGS_ACTION_NAME = "getModelRankingsCached"
NEXT_ROUTER_STATE_TREE = (
    "%5B%22%22%2C%7B%22children%22%3A%5B%22(home)%22%2C%7B%22children%22%3A%5B%22rankings%22%2C%7B%22children%22%3A%5B%22__PAGE__%22%2C%7B%7D%2Cnull%2Cnull%2C0%5D%7D%2Cnull%2Cnull%2C0%5D%7D%2Cnull%2Cnull%2C0%5D%7D%2Cnull%2Cnull%2C20%5D"
)

PRICING_KEYS = (
    "prompt",
    "completion",
    "request",
    "image",
    "audio",
    "web_search",
    "internal_reasoning",
    "input_cache_read",
    "input_cache_write",
)

USER_AGENT = "Mozilla/5.0 (compatible; openrouter-paid-ai-index/0.1)"


@dataclass(frozen=True)
class ModelMaps:
    by_variant_slug: dict[str, dict[str, Any]]
    by_canonical_slug: dict[str, dict[str, Any]]
    by_id: dict[str, dict[str, Any]]
    pricing_by_variant_slug: dict[str, dict[str, str]]
    pricing_by_canonical_slug: dict[str, dict[str, str]]


def fetch_text(url: str, timeout: int) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def fetch_json(url: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def load_text(path_or_url: str, timeout: int) -> str:
    if path_or_url.startswith(("http://", "https://")):
        return fetch_text(path_or_url, timeout)
    return Path(path_or_url).read_text(encoding="utf-8")


def load_json(path_or_url: str, timeout: int) -> dict[str, Any]:
    if path_or_url.startswith(("http://", "https://")):
        return fetch_json(path_or_url, timeout)
    return json.loads(Path(path_or_url).read_text(encoding="utf-8"))


def ranking_type_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    params = urllib.parse.parse_qs(parsed.query)
    value = (params.get("view") or ["week"])[0]
    return value if value in {"day", "week", "month", "trending"} else "week"


def absolute_url(base_url: str, src: str) -> str:
    return src if src.startswith(("http://", "https://")) else urllib.parse.urljoin(base_url, src)


def discover_model_rankings_action_id(html: str, page_url: str, timeout: int) -> str | None:
    scripts = sorted(set(re.findall(r'src="([^"]+\.js[^"]*)"', html)))
    pattern = re.compile(
        r'createServerReference\("([0-9a-f]+)"[^)]*"' + re.escape(MODEL_RANKINGS_ACTION_NAME) + r'"\)'
    )
    for src in scripts:
        full_url = absolute_url(page_url, src)
        if urllib.parse.urlparse(full_url).netloc != urllib.parse.urlparse(page_url).netloc:
            continue
        try:
            script = fetch_text(full_url, timeout)
        except (OSError, urllib.error.URLError):
            continue
        match = pattern.search(script)
        if match:
            return match.group(1)
    return None


def parse_server_action_ranking_data(text: str) -> list[dict[str, Any]]:
    action_ref = "1"
    ref_match = re.search(r'"a"\s*:\s*"\$@([0-9a-fA-F]+)"', text)
    if ref_match:
        action_ref = ref_match.group(1)

    for line in text.splitlines():
        row_id, separator, payload = line.partition(":")
        if separator != ":" or row_id != action_ref:
            continue
        decoded = json.loads(payload)
        if isinstance(decoded, dict) and decoded.get("__kind") == "ERR":
            raise ValueError(f"OpenRouter Server Action returned error: {decoded.get('error')}")
        if (
            isinstance(decoded, list)
            and decoded
            and isinstance(decoded[0], dict)
            and "model_permaslug" in decoded[0]
        ):
            return decoded

    raise ValueError("Could not find OpenRouter ranking rows in Server Action response")


def fetch_ranking_data_via_action(url: str, timeout: int, action_id: str) -> list[dict[str, Any]]:
    body = json.dumps([ranking_type_from_url(url)]).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Accept": "text/x-component",
            "Content-Type": "text/plain;charset=UTF-8",
            "Next-Action": action_id,
            "Next-Router-State-Tree": NEXT_ROUTER_STATE_TREE,
            "Referer": url,
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return parse_server_action_ranking_data(response.read().decode("utf-8"))


def load_ranking_data(path_or_url: str, timeout: int) -> list[dict[str, Any]]:
    if not path_or_url.startswith(("http://", "https://")):
        return extract_ranking_data(load_text(path_or_url, timeout))

    try:
        return fetch_ranking_data_via_action(path_or_url, timeout, MODEL_RANKINGS_ACTION_ID)
    except (OSError, urllib.error.URLError, ValueError):
        html = fetch_text(path_or_url, timeout)
        action_id = discover_model_rankings_action_id(html, path_or_url, timeout)
        if action_id:
            return fetch_ranking_data_via_action(path_or_url, timeout, action_id)
        return extract_ranking_data(html)


def decode_next_flight_chunks(html: str) -> list[str]:
    chunks: list[str] = []
    pattern = re.compile(r"self\.__next_f\.push\(\[1,\"((?:\\.|[^\"\\])*)\"\]\)")
    for match in pattern.finditer(html):
        raw = match.group(1)
        try:
            chunks.append(json.loads(f'"{raw}"'))
        except json.JSONDecodeError:
            continue
    return chunks


def extract_ranking_data(html: str) -> list[dict[str, Any]]:
    decoder = json.JSONDecoder()
    candidates: list[list[dict[str, Any]]] = []

    for chunk in decode_next_flight_chunks(html):
        position = 0
        while True:
            marker = chunk.find('"rankingData"', position)
            if marker < 0:
                break

            start = chunk.rfind("{", 0, marker)
            if start < 0:
                position = marker + 1
                continue

            try:
                obj, end = decoder.raw_decode(chunk[start:])
            except json.JSONDecodeError:
                position = marker + 1
                continue

            ranking_data = obj.get("rankingData") if isinstance(obj, dict) else None
            if (
                isinstance(ranking_data, list)
                and ranking_data
                and isinstance(ranking_data[0], dict)
                and "model_permaslug" in ranking_data[0]
            ):
                candidates.append(ranking_data)

            position = start + end

    if not candidates:
        raise ValueError("Could not find OpenRouter rankingData in rankings HTML")

    return max(candidates, key=len)


def decimal_from(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def int_from(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except Exception:
        return int(decimal_from(value))


def clean_pricing(pricing: dict[str, Any] | None) -> dict[str, str]:
    if not pricing:
        return {}
    return {key: str(value) for key, value in pricing.items() if value is not None}


def is_free_model_id(model_id: str) -> bool:
    return model_id.endswith(":free")


def variant_slug_for_model(model: dict[str, Any]) -> str:
    model_id = str(model.get("id") or "")
    canonical = str(model.get("canonical_slug") or model_id.removesuffix(":free"))
    return f"{canonical}:free" if is_free_model_id(model_id) else canonical


def build_model_maps(models_json: dict[str, Any]) -> ModelMaps:
    by_variant_slug: dict[str, dict[str, Any]] = {}
    by_canonical_slug: dict[str, dict[str, Any]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    pricing_by_variant_slug: dict[str, dict[str, str]] = {}
    pricing_by_canonical_slug: dict[str, dict[str, str]] = {}

    for model in models_json.get("data", []):
        if not isinstance(model, dict):
            continue
        model_id = str(model.get("id") or "")
        canonical = str(model.get("canonical_slug") or model_id.removesuffix(":free"))
        variant_slug = variant_slug_for_model(model)
        pricing = clean_pricing(model.get("pricing"))

        if model_id:
            by_id[model_id] = model
        if canonical:
            by_canonical_slug[canonical] = model
            pricing_by_canonical_slug[canonical] = pricing
        if variant_slug:
            by_variant_slug[variant_slug] = model
            pricing_by_variant_slug[variant_slug] = pricing

    return ModelMaps(
        by_variant_slug=by_variant_slug,
        by_canonical_slug=by_canonical_slug,
        by_id=by_id,
        pricing_by_variant_slug=pricing_by_variant_slug,
        pricing_by_canonical_slug=pricing_by_canonical_slug,
    )


def find_model_for_row(row: dict[str, Any], maps: ModelMaps) -> dict[str, Any] | None:
    variant_slug = str(row.get("variant_permaslug") or "")
    model_slug = str(row.get("model_permaslug") or "")

    return (
        maps.by_variant_slug.get(variant_slug)
        or maps.by_variant_slug.get(model_slug)
        or maps.by_id.get(variant_slug)
        or maps.by_id.get(model_slug)
        or maps.by_canonical_slug.get(model_slug)
    )


def is_free_row(row: dict[str, Any], model: dict[str, Any] | None, pricing: dict[str, str]) -> bool:
    variant = str(row.get("variant") or "").lower()
    variant_slug = str(row.get("variant_permaslug") or "")
    model_id = str(model.get("id") or "") if model else ""
    all_known_prices_zero = bool(pricing) and all(decimal_from(value) == 0 for value in pricing.values())
    return variant == "free" or variant_slug.endswith(":free") or model_id.endswith(":free") or all_known_prices_zero


def estimate_cost(row: dict[str, Any], pricing: dict[str, str]) -> Decimal:
    prompt_tokens = int_from(row.get("total_prompt_tokens"))
    completion_tokens = int_from(row.get("total_completion_tokens"))
    reasoning_tokens = int_from(row.get("total_native_tokens_reasoning"))
    cached_tokens = int_from(row.get("total_native_tokens_cached"))
    request_count = int_from(row.get("count"))
    media_prompt = int_from(row.get("num_media_prompt"))
    media_completion = int_from(row.get("num_media_completion"))
    audio_prompt = int_from(row.get("num_audio_prompt"))
    web_search_requests = int_from(row.get("web_search_requests"))

    return (
        Decimal(prompt_tokens) * decimal_from(pricing.get("prompt"))
        + Decimal(completion_tokens) * decimal_from(pricing.get("completion"))
        + Decimal(reasoning_tokens) * decimal_from(pricing.get("internal_reasoning"))
        + Decimal(cached_tokens) * decimal_from(pricing.get("input_cache_read"))
        + Decimal(request_count) * decimal_from(pricing.get("request"))
        + Decimal(media_prompt + media_completion) * decimal_from(pricing.get("image"))
        + Decimal(audio_prompt) * decimal_from(pricing.get("audio"))
        + Decimal(web_search_requests) * decimal_from(pricing.get("web_search"))
    )


def decimal_string(value: Decimal, places: str = "0.000001") -> str:
    return str(value.quantize(Decimal(places), rounding=ROUND_HALF_UP))


def report_decimal(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,.2f}"


def report_timestamp(value: Any) -> str:
    if not value:
        return "未知"
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.replace(microsecond=0).isoformat()
    except ValueError:
        return re.sub(r"(\d{2}:\d{2}:\d{2})\.\d+", r"\1", text)


def money(value: Decimal) -> str:
    formatted = f"${report_decimal(value)}"
    absolute = abs(value)
    if absolute >= Decimal("100000000"):
        return f"{formatted}（约 {report_decimal(value / Decimal('100000000'))} 亿美元）"
    if absolute >= Decimal("10000"):
        return f"{formatted}（约 {report_decimal(value / Decimal('10000'))} 万美元）"
    return formatted


def ratio(current: Decimal, previous: Decimal) -> Decimal | None:
    if previous == 0:
        return None
    return (current - previous) / previous


def percent(value: Decimal | None) -> str:
    if value is None:
        return "无可比基准"
    return f"{decimal_string(value * Decimal('100'), '0.01')}%"


def format_tokens(value: int) -> str:
    units = (("T", 10**12), ("B", 10**9), ("M", 10**6), ("K", 10**3))
    for suffix, factor in units:
        if abs(value) >= factor:
            return f"{Decimal(value) / Decimal(factor):.2f}{suffix}"
    return str(value)


def price_per_million_text_tokens(row: dict[str, Any], pricing: dict[str, str]) -> Decimal:
    prompt_tokens = int_from(row.get("total_prompt_tokens"))
    completion_tokens = int_from(row.get("total_completion_tokens"))
    text_tokens = prompt_tokens + completion_tokens
    if text_tokens <= 0:
        return Decimal("0")
    text_cost = (
        Decimal(prompt_tokens) * decimal_from(pricing.get("prompt"))
        + Decimal(completion_tokens) * decimal_from(pricing.get("completion"))
    )
    return text_cost / Decimal(text_tokens) * Decimal(1_000_000)


def extract_base_prices(base_snapshot: dict[str, Any] | None) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    if not base_snapshot:
        return {}, {}
    return (
        base_snapshot.get("pricing_by_variant_slug", {}) or {},
        base_snapshot.get("pricing_by_canonical_slug", {}) or {},
    )


def build_snapshot(
    ranking_data: list[dict[str, Any]],
    models_json: dict[str, Any],
    *,
    base_snapshot: dict[str, Any] | None = None,
    premium_threshold_per_mtoken: Decimal = Decimal("3.0"),
) -> dict[str, Any]:
    maps = build_model_maps(models_json)
    base_by_variant, base_by_canonical = extract_base_prices(base_snapshot)
    entries: list[dict[str, Any]] = []

    for rank, row in enumerate(ranking_data, start=1):
        model = find_model_for_row(row, maps)
        variant_slug = str(row.get("variant_permaslug") or "")
        model_slug = str(row.get("model_permaslug") or "")
        raw_pricing = clean_pricing(model.get("pricing")) if model else {}
        is_free = is_free_row(row, model, raw_pricing)
        pricing = {} if is_free else raw_pricing
        base_pricing = {} if is_free else base_by_variant.get(variant_slug) or base_by_canonical.get(model_slug) or pricing
        has_positive_price = any(decimal_from(value) > 0 for value in pricing.values())
        is_paid = (not is_free) and has_positive_price
        prompt_tokens = int_from(row.get("total_prompt_tokens"))
        completion_tokens = int_from(row.get("total_completion_tokens"))
        visible_tokens = prompt_tokens + completion_tokens
        current_cost = estimate_cost(row, pricing) if pricing else Decimal("0")
        constant_cost = estimate_cost(row, base_pricing) if base_pricing else Decimal("0")
        blended_price = price_per_million_text_tokens(row, pricing)

        entries.append(
            {
                "rank": rank,
                "date": row.get("date"),
                "model_id": model.get("id") if model else None,
                "model_name": model.get("name") if model else None,
                "model_permaslug": model_slug,
                "variant_permaslug": variant_slug,
                "variant": row.get("variant"),
                "matched_model": model is not None,
                "is_free": is_free,
                "is_paid": is_paid,
                "is_premium_paid": is_paid and blended_price >= premium_threshold_per_mtoken,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "visible_tokens": visible_tokens,
                "reasoning_tokens": int_from(row.get("total_native_tokens_reasoning")),
                "cached_tokens": int_from(row.get("total_native_tokens_cached")),
                "request_count": int_from(row.get("count")),
                "media_prompt_count": int_from(row.get("num_media_prompt")),
                "media_completion_count": int_from(row.get("num_media_completion")),
                "audio_prompt_count": int_from(row.get("num_audio_prompt")),
                "tool_call_count": int_from(row.get("total_tool_calls")),
                "change": row.get("change"),
                "pricing": pricing,
                "base_pricing": base_pricing,
                "text_price_per_million_usd": decimal_string(blended_price),
                "estimated_cost_usd": decimal_string(current_cost),
                "constant_price_cost_usd": decimal_string(constant_cost),
            }
        )

    paid_entries = [entry for entry in entries if entry["is_paid"]]
    free_entries = [entry for entry in entries if entry["is_free"]]
    unmatched_standard_entries = [
        entry for entry in entries if (not entry["matched_model"]) and (not entry["is_free"])
    ]
    unmatched_standard_token_entries = [
        entry for entry in unmatched_standard_entries if entry["visible_tokens"] > 0
    ]
    paid_tokens = sum(entry["visible_tokens"] for entry in paid_entries)
    free_tokens = sum(entry["visible_tokens"] for entry in free_entries)
    total_tokens = sum(entry["visible_tokens"] for entry in entries)
    paid_cost = sum((Decimal(entry["estimated_cost_usd"]) for entry in paid_entries), Decimal("0"))
    constant_cost = sum((Decimal(entry["constant_price_cost_usd"]) for entry in paid_entries), Decimal("0"))
    premium_tokens = sum(entry["visible_tokens"] for entry in paid_entries if entry["is_premium_paid"])

    ranking_date = next((entry["date"] for entry in entries if entry.get("date")), None)
    paid_share = Decimal(paid_tokens) / Decimal(total_tokens) if total_tokens else Decimal("0")
    premium_share = Decimal(premium_tokens) / Decimal(paid_tokens) if paid_tokens else Decimal("0")

    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "rankings_url": RANKINGS_URL,
            "models_url": MODELS_URL,
        },
        "ranking_date": ranking_date,
        "assumptions": {
            "paid_token_index": "prompt_tokens + completion_tokens for paid, non-free variants",
            "revenue_proxy": "public ranking usage multiplied by public model pricing; unobserved discounts and private deals are not included",
            "cached_tokens": "total_native_tokens_cached is priced as input_cache_read when available",
            "tool_calls": "total_tool_calls is reported but not priced unless a future ranking field exposes web_search_requests",
            "premium_threshold_per_mtoken_usd": str(premium_threshold_per_mtoken),
        },
        "totals": {
            "ranked_model_variants": len(entries),
            "matched_model_variants": sum(1 for entry in entries if entry["matched_model"]),
            "paid_model_variants": len(paid_entries),
            "free_model_variants": len(free_entries),
            "unmatched_standard_variants": len(unmatched_standard_entries),
            "unmatched_standard_token_variants": len(unmatched_standard_token_entries),
            "unmatched_standard_visible_tokens": sum(
                entry["visible_tokens"] for entry in unmatched_standard_token_entries
            ),
            "total_visible_tokens": total_tokens,
            "paid_visible_tokens": paid_tokens,
            "free_visible_tokens": free_tokens,
            "paid_token_share": decimal_string(paid_share),
            "premium_paid_visible_tokens": premium_tokens,
            "premium_paid_token_share": decimal_string(premium_share),
            "revenue_proxy_usd": decimal_string(paid_cost),
            "constant_price_revenue_usd": decimal_string(constant_cost),
            "unpriced_tool_calls": sum(entry["tool_call_count"] for entry in paid_entries),
        },
        "top_paid_by_cost": sorted(
            paid_entries,
            key=lambda entry: Decimal(entry["estimated_cost_usd"]),
            reverse=True,
        )[:20],
        "top_paid_by_tokens": sorted(paid_entries, key=lambda entry: entry["visible_tokens"], reverse=True)[:20],
        "top_free_by_tokens": sorted(free_entries, key=lambda entry: entry["visible_tokens"], reverse=True)[:20],
        "unmatched_standard_entries": sorted(
            unmatched_standard_entries,
            key=lambda entry: entry["visible_tokens"],
            reverse=True,
        )[:50],
        "pricing_by_variant_slug": maps.pricing_by_variant_slug,
        "pricing_by_canonical_slug": maps.pricing_by_canonical_slug,
        "entries": entries,
    }


def compare_totals(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, str]:
    if not previous:
        return {}

    current_totals = current.get("totals", {})
    previous_totals = previous.get("totals", {})
    fields = (
        "paid_visible_tokens",
        "free_visible_tokens",
        "revenue_proxy_usd",
        "constant_price_revenue_usd",
        "premium_paid_visible_tokens",
    )
    result: dict[str, str] = {}
    for field in fields:
        current_value = decimal_from(current_totals.get(field))
        previous_value = decimal_from(previous_totals.get(field))
        result[field] = percent(ratio(current_value, previous_value))
    return result


def render_table(entries: list[dict[str, Any]], limit: int, metric: str) -> list[str]:
    lines = ["| # | 模型 | Token | 估算费用 | 文本 $/百万 Token |", "| --- | --- | ---: | ---: | ---: |"]
    for index, entry in enumerate(entries[:limit], start=1):
        name = entry.get("model_name") or entry.get("variant_permaslug") or entry.get("model_permaslug")
        lines.append(
            "| {index} | {name} | {tokens} | {cost} | {price} |".format(
                index=index,
                name=str(name).replace("|", "\\|"),
                tokens=format_tokens(int_from(entry.get("visible_tokens"))),
                cost=money(Decimal(str(entry.get(metric, "0")))),
                price=report_decimal(Decimal(str(entry.get("text_price_per_million_usd", "0")))),
            )
        )
    return lines


def render_research_framework() -> list[str]:
    return [
        "## 研究框架",
        "",
        "- 本报告衡量的是 OpenRouter 平台上的付费推理需求，而不是完整的 AI 能力进步。",
        "- 付费模型更接近生产工作流和商业化强度；免费模型更适合作为实验热度和潜在转化信号，因此两条线分开观察。",
        "- 收入代理估算可以观察商业化强度，但会受价格变化和模型结构迁移影响；固定价格收入估算用于剥离价格变化影响。",
        "- 高端付费 Token 占比用于观察用户是否继续把复杂任务交给更贵、更强的模型。",
        "- OpenRouter 是开发者/API/agent 工作流的重要观察窗口，但不能代表 ChatGPT 网页端、企业直连、本地部署或其他平台的全市场。",
    ]


def render_weekly_read(snapshot: dict[str, Any], comparisons: dict[str, str]) -> list[str]:
    totals = snapshot["totals"]
    paid_share = Decimal(totals["paid_token_share"]) * Decimal("100")
    premium_share = Decimal(totals["premium_paid_token_share"]) * Decimal("100")
    paid_share_text = report_decimal(paid_share)
    premium_share_text = report_decimal(premium_share)
    paid_state = "占主导" if paid_share >= Decimal("70") else "占比较高" if paid_share >= Decimal("50") else "尚未占主导"

    lines = [
        "## 本周读法",
        "",
        f"- 付费模型贡献了 {paid_share_text}% 的可见 Token，当前在 OpenRouter 榜单中{paid_state}，更适合解读为生产化/商业化使用信号。",
        f"- 免费模型贡献 {format_tokens(totals['free_visible_tokens'])} 可见 Token，主要用于观察试用、扩散和社区热度，不直接并入收入代理估算。",
        f"- 高端付费 Token 占比为 {premium_share_text}%，可以作为复杂任务和高价模型偏好的辅助观察线。",
    ]

    if comparisons:
        lines.extend(
            [
                f"- 与上一期相比，付费 Token 需求变化为 {comparisons['paid_visible_tokens']}，固定价格收入估算变化为 {comparisons['constant_price_revenue_usd']}。",
                "- 趋势判断应优先看付费 Token 与固定价格收入是否同向变化，再看免费热度是否能转化为付费需求。",
            ]
        )
    else:
        lines.append(
            "- 当前未提供上一期 `--compare-json`，本期更适合作为横截面基线；不要单独用一周数据判断加速、停滞或倒退。"
        )

    return lines


def render_trend_rules() -> list[str]:
    return [
        "## 趋势判读规则",
        "",
        "- 加速：付费 Token、固定价格收入和高端付费 Token 占比同步上升，且付费模型供应商更分散。",
        "- 停滞：付费 Token 持平，总费用增长主要来自涨价或少数昂贵模型，或免费热度高但付费转化弱。",
        "- 倒退：付费 Token 和固定价格收入同步下降，用户迁移到免费或极低价模型，高端付费份额下降。",
    ]


def render_markdown_report(
    snapshot: dict[str, Any],
    *,
    previous_snapshot: dict[str, Any] | None = None,
    top: int = 10,
) -> str:
    totals = snapshot["totals"]
    comparisons = compare_totals(snapshot, previous_snapshot)
    lines = [
        "# OpenRouter 付费 AI 推理指数",
        "",
        f"- 榜单日期：{snapshot.get('ranking_date') or '未知'}",
        f"- 生成时间：{report_timestamp(snapshot.get('generated_at'))}",
        f"- 榜单模型变体数：{totals['ranked_model_variants']}（{totals['matched_model_variants']} 个匹配到价格）",
        "",
        "## 指标总览",
        "",
        f"- 付费 Token 需求指数：{format_tokens(totals['paid_visible_tokens'])}",
        f"- 免费使用指数：{format_tokens(totals['free_visible_tokens'])}",
        f"- 付费 Token 占比：{Decimal(totals['paid_token_share']) * Decimal('100'):.2f}%",
        f"- 收入代理估算：{money(Decimal(totals['revenue_proxy_usd']))}",
        f"- 固定价格收入估算：{money(Decimal(totals['constant_price_revenue_usd']))}",
        f"- 高端付费 Token 占比：{Decimal(totals['premium_paid_token_share']) * Decimal('100'):.2f}%",
    ]

    if comparisons:
        lines.extend(
            [
                "",
                "## 对比变化",
                "",
                f"- 付费 Token 需求变化：{comparisons['paid_visible_tokens']}",
                f"- 免费使用变化：{comparisons['free_visible_tokens']}",
                f"- 收入代理估算变化：{comparisons['revenue_proxy_usd']}",
                f"- 固定价格收入估算变化：{comparisons['constant_price_revenue_usd']}",
                f"- 高端付费 Token 变化：{comparisons['premium_paid_visible_tokens']}",
        ]
    )

    lines.extend(
        [
            "",
            *render_research_framework(),
            "",
            *render_weekly_read(snapshot, comparisons),
            "",
            *render_trend_rules(),
            "",
            "## 按估算费用排序的付费模型",
            "",
            *render_table(snapshot["top_paid_by_cost"], top, "estimated_cost_usd"),
            "",
            "## 按 Token 排序的付费模型",
            "",
            *render_table(snapshot["top_paid_by_tokens"], top, "estimated_cost_usd"),
            "",
            "## 按 Token 排序的免费模型",
            "",
            *render_table(snapshot["top_free_by_tokens"], top, "estimated_cost_usd"),
            "",
            "## 计算口径",
            "",
            "- 付费 Token 需求指数 = Σ(prompt_tokens + completion_tokens)，仅统计非免费且公开价格大于 0 的模型变体。",
            "- 免费使用指数 = Σ(prompt_tokens + completion_tokens)，仅统计 `:free` 或价格为 0 的模型变体。",
            "- 收入代理估算 = Σ(prompt_tokens × prompt_price + completion_tokens × completion_price + reasoning_tokens × internal_reasoning_price + cached_tokens × input_cache_read_price + request_count × request_price + image/audio/web_search 等公开价格项)。",
            "- 固定价格收入估算 = 当前用量 × `--base-json` 中保存的基准周价格；没有传入 `--base-json` 时等同于当前公开价格估算。",
            "- 文本 $/百万 Token = (prompt_tokens × prompt_price + completion_tokens × completion_price) ÷ (prompt_tokens + completion_tokens) × 1,000,000。",
            "- 高端付费 Token 占比 = 混合文本价格不低于 `--premium-threshold-per-mtoken` 的付费模型 Token ÷ 全部付费模型 Token。",
            "",
            "## 注意事项",
            "",
            "- 这是一组付费推理需求代理指标，不是完整的 AI 能力指数。",
            "- OpenRouter 公开榜单反映的是该平台的使用情况，不能代表整个 AI 市场。",
            "- 收入代理值基于公开价格和公开榜单字段估算，无法覆盖私有折扣或单独商务协议。",
            "- 建议每周保存 JSON 快照，并用第一周快照作为 `--base-json`，以剥离后续价格变化的影响。",
        ]
    )

    if totals["unmatched_standard_token_variants"]:
        lines.extend(
            [
                "",
                "## 警告",
                "",
                "- 有 {count} 个非免费榜单变体、合计 {tokens} 可见 Token 未匹配到当前模型价格。".format(
                    count=totals["unmatched_standard_token_variants"],
                    tokens=format_tokens(totals["unmatched_standard_visible_tokens"]),
                ),
            ]
        )

    return "\n".join(lines) + "\n"


def write_output(path: str | None, content: str) -> None:
    if not path:
        return
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a weekly Paid AI Inference Index from OpenRouter public rankings.",
    )
    parser.add_argument("--ranking-url", default=RANKINGS_URL, help="OpenRouter rankings URL or local HTML file")
    parser.add_argument("--models-url", default=MODELS_URL, help="OpenRouter models API URL or local JSON file")
    parser.add_argument("--base-json", help="Base snapshot for constant-price revenue")
    parser.add_argument("--compare-json", help="Previous snapshot for trend comparison")
    parser.add_argument("--output-json", help="Write the full snapshot JSON to this path")
    parser.add_argument("--output-md", help="Write a Markdown report to this path")
    parser.add_argument("--top", type=int, default=10, help="Rows to show in each Markdown top table")
    parser.add_argument("--timeout", type=int, default=30, help="Network timeout in seconds")
    parser.add_argument(
        "--premium-threshold-per-mtoken",
        default="3.0",
        help="Blended text price threshold in USD per million tokens for premium paid share",
    )
    parser.add_argument("--quiet", action="store_true", help="Do not print the Markdown report to stdout")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        ranking_data = load_ranking_data(args.ranking_url, args.timeout)
        models_json = load_json(args.models_url, args.timeout)
        base_snapshot = load_json(args.base_json, args.timeout) if args.base_json else None
        previous_snapshot = load_json(args.compare_json, args.timeout) if args.compare_json else None

        snapshot = build_snapshot(
            ranking_data,
            models_json,
            base_snapshot=base_snapshot,
            premium_threshold_per_mtoken=decimal_from(args.premium_threshold_per_mtoken),
        )
        snapshot["sources"]["rankings_url"] = args.ranking_url
        snapshot["sources"]["models_url"] = args.models_url

        json_text = json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True)
        report = render_markdown_report(snapshot, previous_snapshot=previous_snapshot, top=args.top)

        write_output(args.output_json, json_text + "\n")
        write_output(args.output_md, report)
        if not args.quiet:
            print(report, end="")
        return 0
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
