"""AI 顾问层：BYOK 可选端点，候选生成与解释（ADR-0003：AI 只当顾问）。

红线落地（design §3）：
- 配置三元组（MOUDO_AI_BASE_URL / MOUDO_AI_API_KEY / MOUDO_AI_MODEL）缺一即视为
  未配置，不发起任何网络请求；
- 发送载荷仅含 SQL 文本与 schema 摘要（表/列/索引元数据），绝不含采样数据行；
- 超时/解析失败/网络异常一律降级为空候选（fail-safe），不阻塞报告。
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from modou.optimize.candidates import IndexCandidate
from modou.snapshot.model import Snapshot

ENV_BASE_URL = "MOUDO_AI_BASE_URL"
ENV_API_KEY = "MOUDO_AI_API_KEY"
ENV_MODEL = "MOUDO_AI_MODEL"

DEFAULT_TIMEOUT_SECONDS = 30.0

_JSON_ARRAY_PATTERN = re.compile(r"\[.*\]", re.DOTALL)

Transport = Callable[[str, str, dict, float], dict]


def _default_transport(url: str, api_key: str, payload: dict, timeout: float) -> dict[str, Any]:
    """OpenAI 兼容端点调用（stdlib，无额外依赖；未配置时永不执行）。"""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
    try:
        return json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"invalid AI endpoint response: {exc}") from exc


@dataclass
class AdvisorConfig:
    base_url: str
    api_key: str
    model: str


def config_from_env(env: Mapping[str, str]) -> AdvisorConfig | None:
    """三元组缺一即未配置（含空白值）：未配置 = 零网络请求。"""
    base_url = (env.get(ENV_BASE_URL) or "").strip()
    api_key = (env.get(ENV_API_KEY) or "").strip()
    model = (env.get(ENV_MODEL) or "").strip()
    if not base_url or not api_key or not model:
        return None
    return AdvisorConfig(base_url=base_url, api_key=api_key, model=model)


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
    max_candidates: int = 5,
) -> dict[str, Any]:
    """构造 OpenAI 兼容 chat/completions 请求体（JSON 输出约束在提示词中）。"""
    system = (
        "You are a MySQL index and query advisor. Given one slow SQL statement and schema metadata, "
        f"propose at most {max_candidates} concrete suggestions. Respond with ONLY a JSON array; "
        'each item is either {"type":"index","table":"<table name>","columns":["<col>",...]} '
        "for a secondary index candidate (leftmost equality columns first, then one range column) "
        'or {"type":"rewrite","sql":"<rewritten sql>"} for a query rewrite. '
        "Do not propose indexes that already exist in the schema. No prose."
    )
    user = {
        "statement": statement_sql,
        "schema": schema_summary,
    }
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
    transport: Transport = _default_transport,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[IndexCandidate]:
    """未配置直接返回空（零网络）；已配置则拉取候选，失败降级为空。"""
    if config is None:
        return []
    return fetch_candidates(
        config,
        statement_sql,
        schema_summary,
        transport=transport,
        timeout_seconds=timeout_seconds,
    )


def fetch_candidates(
    config: AdvisorConfig,
    statement_sql: str,
    schema_summary: list[dict[str, Any]],
    *,
    transport: Transport = _default_transport,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[IndexCandidate]:
    """调用 BYOK 端点并解析候选；任何失败降级为空清单（fail-safe，不阻塞报告）。"""
    payload = build_request_payload(config, statement_sql, schema_summary)
    try:
        response = transport(
            config.base_url.rstrip("/") + "/chat/completions",
            config.api_key,
            payload,
            timeout_seconds,
        )
    except (OSError, ValueError, TypeError, KeyError):
        return []
    try:
        content = str(response["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError):
        return []
    return parse_candidate_content(content)


def parse_candidate_content(content: str) -> list[IndexCandidate]:
    """从模型回复提取 JSON 数组并解析候选；不可解析/形态不对的条目逐条丢弃。"""
    match = _JSON_ARRAY_PATTERN.search(content)
    if match is None:
        return []
    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
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
