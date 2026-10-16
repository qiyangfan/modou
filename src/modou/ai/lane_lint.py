"""lint 残留语义评审（内置通道，design §5）：规则引擎之后，残留语句分包送 AI。

- 残留面由 lint 引擎单趟产出（LintResult.residuals，与命中同源）——本模块只
  做分包与受控调用，不重读文件、不重跑规则；
- 上下文 = 变更分包（bundler）+ 已命中规则注入（injector）；审核车道纯静态、
  无库连接，schema 上下文不适用；
- 输出 = 结构化 JSON 逐条校验（幻觉定位与空观点逐条丢弃）；调用失败或回复
  不可解析 → 该批降级为 degraded 观点（fail-safe 标注原因，不静默缺席）；
- 本模块只产出 report.opinions.AiOpinion，永不影响退出码。
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
    """残留语句分包评审：每批一轮单turn调用，顺序聚合（并发由调用方按批展开）。"""
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
        # 回复不可解析同属调用失败（spec「调用失败降级」）：标注原因，不静默缺席
        return [degraded(LANE, _batch_subject(batch), config.model, "unparseable reply (no JSON array)")]
    opinions: list[AiOpinion] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        subject = item.get("subject")
        text = item.get("opinion")
        if not isinstance(subject, str) or subject not in subjects:
            continue  # 幻觉定位：指向批次外对象的条目丢弃
        if not isinstance(text, str) or not text.strip():
            continue
        opinions.append(AiOpinion(lane=LANE, subject=subject, opinion=text.strip(), model=config.model))
    return opinions


def _batch_subject(batch: list[StatementUnit]) -> str:
    if len(batch) == 1:
        return batch[0].subject
    return f"{batch[0].subject}~{batch[-1].subject}"
