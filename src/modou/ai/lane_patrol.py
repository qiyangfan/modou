"""patrol 跨信号综合叙事（内置通道，design §5）：漂移 + 未用索引 + 慢日志指纹 →
AI 跨信号洞察。

- 输入是 patrol/summary 的确定性 digest（结构性事实），AI 只做规则表达不了的
  关联与取舍（如「新增索引与慢日志扫描相互印证」「漂移删除与未用索引矛盾」）；
- 无信号零调用；输出逐条校验（仅接受 cross-signal 主题）；失败降级不阻塞报告；
- 只产出 report.opinions.AiOpinion，退出码免疫。
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
    """对综合摘要做跨信号叙事；无信号零调用，失败降级为单条 degraded 观点。"""
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
        # 回复不可解析同属调用失败（spec「调用失败降级」）：标注原因，不静默缺席
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
