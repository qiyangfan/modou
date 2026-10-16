"""优化车道 · AI 候选生成（内置通道的 optimize 侧）：提示词、候选解析与失败降级。

职责面见 ADR-0009（AI 当分析师），实证关与退出码条款见 ADR-0003（继续有效）。
BYOK 客户端已收拢进 modou.ai.client（v0.5，行为不变）；本模块只保留优化车道
的提示词与候选结构化解析。配置三元组缺一即未配置（零网络）；发送载荷仅含
SQL 文本与 schema 元数据；失败一律降级为空候选（fail-safe，不阻塞报告）。
"""

from __future__ import annotations

import json
from typing import Any

from modou.ai.client import (
    DEFAULT_TIMEOUT_SECONDS,
    ENV_API_KEY,
    ENV_BASE_URL,
    ENV_MODEL,
    AiCallError,
    AiConfig,
    Transport,
    complete,
    config_from_env,
    default_transport,
    extract_json_array,
)
from modou.optimize.candidates import IndexCandidate
from modou.snapshot.model import Snapshot

# 向后兼容：历史调用方（CLI/测试）从本模块导入配置与传输类型
AdvisorConfig = AiConfig


def build_schema_summary(snapshot: Snapshot, databases: set[str]) -> list[dict[str, Any]]:
    """schema 摘要（仅元数据）：库 → 表 → 列定义与索引，供 AI 理解结构。"""
    summary: list[dict[str, Any]] = []
    for db_name in sorted(snapshot.databases):
        if db_name not in databases:
            continue
        inventory = snapshot.databases[db_name]
        for table_name in sorted(inventory.tables):
            table = inventory.tables[table_name]
            summary.append(
                {
                    "database": db_name,
                    "table": table_name,
                    "engine": table.engine,
                    "columns": [
                        f"{col.name} {col.column_type}{'' if col.nullable else ' NOT NULL'}" for col in table.columns
                    ],
                    "indexes": [
                        f"{index.name}{' UNIQUE' if index.unique else ''} "
                        + "("
                        + ", ".join(part.column for part in index.parts if part.column)
                        + ")"
                        for index in table.indexes
                    ],
                }
            )
    return summary


def build_request_payload(
    config: AdvisorConfig,
    statement_sql: str,
    schema_summary: list[dict[str, Any]],
    *,
    explain_facts: dict[str, Any] | None = None,
    max_candidates: int = 5,
) -> dict[str, Any]:
    """构造 OpenAI 兼容 chat/completions 请求体（JSON 输出约束在提示词中）。

    explain_facts 是影子库基线 EXPLAIN 的预取事实（受控多轮的确定性半区，v0.5）：
    候选生成基于实测计划而非模型猜测；缺省 None 保持 v0.2 one-shot 形态。
    """
    system = (
        "You are a MySQL index and query advisor. Given one slow SQL statement and schema metadata, "
        f"propose at most {max_candidates} concrete suggestions. Respond with ONLY a JSON array; "
        'each item is either {"type":"index","table":"<table name>","columns":["<col>",...]} '
        "for a secondary index candidate (leftmost equality columns first, then one range column) "
        'or {"type":"rewrite","sql":"<rewritten sql>"} for a query rewrite. '
        "Do not propose indexes that already exist in the schema. No prose."
    )
    user: dict[str, Any] = {
        "statement": statement_sql,
        "schema": schema_summary,
    }
    if explain_facts is not None:
        system += (
            " Baseline EXPLAIN facts from the shadow database are provided; use them to target the "
            "expensive access paths instead of guessing."
        )
        user["explain_facts"] = explain_facts
    return {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        "temperature": 0,
    }


def maybe_fetch_candidates(
    config: AdvisorConfig | None,
    statement_sql: str,
    schema_summary: list[dict[str, Any]],
    *,
    explain_facts: dict[str, Any] | None = None,
    transport: Transport = default_transport,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[IndexCandidate]:
    """未配置直接返回空（零网络）；已配置则拉取候选，失败降级为空。"""
    if config is None:
        return []
    return fetch_candidates(
        config,
        statement_sql,
        schema_summary,
        explain_facts=explain_facts,
        transport=transport,
        timeout_seconds=timeout_seconds,
    )


def fetch_candidates(
    config: AdvisorConfig,
    statement_sql: str,
    schema_summary: list[dict[str, Any]],
    *,
    explain_facts: dict[str, Any] | None = None,
    transport: Transport = default_transport,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[IndexCandidate]:
    """调用 BYOK 端点并解析候选；任何失败降级为空清单（fail-safe，不阻塞报告）。"""
    payload = build_request_payload(config, statement_sql, schema_summary, explain_facts=explain_facts)
    try:
        content = complete(config, payload, transport=transport, timeout_seconds=timeout_seconds)
    except AiCallError:
        return []
    return parse_candidate_content(content)


def parse_candidate_content(content: str) -> list[IndexCandidate]:
    """从模型回复提取 JSON 数组并解析候选；不可解析/形态不对的条目逐条丢弃。"""
    items = extract_json_array(content)
    if items is None:
        return []
    candidates: list[IndexCandidate] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "index":
            table = item.get("table")
            columns = item.get("columns")
            if isinstance(table, str) and table and isinstance(columns, list) and columns:
                normalized = [str(col) for col in columns if isinstance(col, str) and col]
                if normalized:
                    candidates.append(
                        IndexCandidate(
                            database=None,
                            table=table,
                            columns=normalized,
                            reason="AI 建议索引",
                            source="ai",
                            kind="index",
                        )
                    )
        elif kind == "rewrite":
            sql = item.get("sql")
            if isinstance(sql, str) and sql.strip():
                candidates.append(
                    IndexCandidate(
                        database=None,
                        table="",
                        columns=[],
                        reason="AI 改写建议",
                        source="ai",
                        kind="rewrite",
                        sql=sql.strip().rstrip(";"),
                    )
                )
    return candidates


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "ENV_API_KEY",
    "ENV_BASE_URL",
    "ENV_MODEL",
    "AdvisorConfig",
    "Transport",
    "build_request_payload",
    "build_schema_summary",
    "config_from_env",
    "fetch_candidates",
    "maybe_fetch_candidates",
    "parse_candidate_content",
]
