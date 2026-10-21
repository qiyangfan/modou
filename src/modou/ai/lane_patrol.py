"""根据确定性巡检摘要生成跨信号 AI 观点。

无巡检信号时不调用模型；调用失败降级为观点，不影响退出码。
"""

from __future__ import annotations

from modou.ai.client import (
    DEFAULT_TIMEOUT_SECONDS,
    AiCallError,
    AiConfig,
    Transport,
    chat_content,
    default_transport,
    extract_json_array,
)
from modou.report.opinions import AiOpinion, degraded

LANE = "patrol"
SUBJECT = "cross-signal"

_SYSTEM_PROMPT = (
    "You are a senior MySQL DBA synthesizing patrol signals: structural drift, index usage layers "
    "and slow-query fingerprints. Report only cross-signal insight static summaries cannot express: "
    "correlations (a new index vs a slow scan; a dropped object vs an unused index), contradictions, "
    "priorities and concrete next actions. Respond with ONLY a JSON array: "
    '[{"subject":"cross-signal","opinion":"<short paragraph in Chinese>"}]. No prose outside JSON.'
)


def narrativize(
    summary_json: dict,
    *,
    config: AiConfig,
    transport: Transport = default_transport,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[AiOpinion]:
    """对巡检摘要生成跨信号观点；无信号不调用，失败降级为一条 degraded 观点。"""
    signals = summary_json.get("signals") or {}
    if not signals:
        return []
    user_payload = {"inputs": summary_json.get("inputs") or {}, "signals": signals}
    try:
        content = chat_content(
            config,
            system=_SYSTEM_PROMPT,
            user_payload=user_payload,
            transport=transport,
            timeout_seconds=timeout_seconds,
        )
    except AiCallError as exc:
        return [degraded(LANE, SUBJECT, config.model, str(exc))]
    items = extract_json_array(content)
    if items is None:
        # 回复不可解析时按调用失败降级。
        return [degraded(LANE, SUBJECT, config.model, "unparseable reply (no JSON array)")]
    opinions: list[AiOpinion] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        subject = item.get("subject")
        text = item.get("opinion")
        if subject != SUBJECT:
            continue
        if not isinstance(text, str) or not text.strip():
            continue
        opinions.append(AiOpinion(lane=LANE, subject=SUBJECT, opinion=text.strip(), model=config.model))
    return opinions
