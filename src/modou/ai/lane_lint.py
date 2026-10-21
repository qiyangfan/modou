"""评审 lint 引擎未命中的残留语句。

只产出观点；无效条目丢弃，批次调用失败降级，不影响退出码。
"""

from __future__ import annotations

from collections.abc import Sequence

from modou.ai.bundler import DEFAULT_MAX_CHARS, DEFAULT_MAX_STATEMENTS, StatementUnit, bundle_units
from modou.ai.client import (
    DEFAULT_TIMEOUT_SECONDS,
    AiCallError,
    AiConfig,
    Transport,
    chat_content,
    default_transport,
    extract_json_array,
)
from modou.ai.injector import render_rule_context
from modou.lint.engine import Hit
from modou.report.opinions import AiOpinion, degraded

LANE = "lint"

_SYSTEM_PROMPT = (
    "You are a senior MySQL migration reviewer doing SEMANTIC review of SQL statements that already "
    "passed all static rules. Report only risks static rules cannot express: cross-statement ordering "
    "or dependency conflicts, intent mismatch with the change, destructive data effects, lock or "
    "replication hazards. Respond with ONLY a JSON array; each item is "
    '{"subject":"<subject exactly as given>","opinion":"<one short paragraph in Chinese>"} '
    "for statements that deserve a remark; omit statements with nothing to flag. No prose outside JSON."
)


def review_residual(
    units: Sequence[StatementUnit],
    hits: Sequence[Hit],
    config: AiConfig,
    *,
    transport: Transport = default_transport,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_statements: int = DEFAULT_MAX_STATEMENTS,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[AiOpinion]:
    """分包评审残留语句，按批次顺序聚合并返回观点。"""
    if not units:
        return []
    rule_context = render_rule_context(hits)
    opinions: list[AiOpinion] = []
    for batch in bundle_units(list(units), max_statements=max_statements, max_chars=max_chars):
        opinions.extend(
            _review_batch(batch, rule_context, config, transport=transport, timeout_seconds=timeout_seconds)
        )
    return opinions


def _review_batch(
    batch: list[StatementUnit],
    rule_context: str,
    config: AiConfig,
    *,
    transport: Transport,
    timeout_seconds: float,
) -> list[AiOpinion]:
    subjects = {unit.subject for unit in batch}
    user_payload: dict = {"statements": [{"subject": unit.subject, "sql": unit.sql} for unit in batch]}
    if rule_context:
        user_payload["static_rule_hits"] = rule_context
    try:
        content = chat_content(
            config,
            system=_SYSTEM_PROMPT,
            user_payload=user_payload,
            transport=transport,
            timeout_seconds=timeout_seconds,
        )
    except AiCallError as exc:
        return [degraded(LANE, _batch_subject(batch), config.model, str(exc))]
    items = extract_json_array(content)
    if items is None:
        # 回复不可解析时按调用失败降级。
        return [degraded(LANE, _batch_subject(batch), config.model, "unparseable reply (no JSON array)")]
    opinions: list[AiOpinion] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        subject = item.get("subject")
        text = item.get("opinion")
        if not isinstance(subject, str) or subject not in subjects:
            continue  # 丢弃指向批次外对象的条目
        if not isinstance(text, str) or not text.strip():
            continue
        opinions.append(AiOpinion(lane=LANE, subject=subject, opinion=text.strip(), model=config.model))
    return opinions


def _batch_subject(batch: list[StatementUnit]) -> str:
    if len(batch) == 1:
        return batch[0].subject
    return f"{batch[0].subject}~{batch[-1].subject}"
