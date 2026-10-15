"""优化实证管线：输入校验 → 影子库采样灌入 → 逐候选「基线 → 应用 → 刷新统计 →
复测」→ 两级状态判定 → 按库分组报告。

流程口径（v0.2 design §2/§4，2026-10 调研核实）：
- 空表 EXPLAIN 无代价差异：输入必须为采样快照（无数据 → 输入错误，指引重采）；
- InnoDB 统计为随机采样且 ADD INDEX 无条件刷新统计：基线与复测两侧各自显式
  ANALYZE 拉平口径，候选落地后（删除后同理）再刷新一次；
- 实证关（ADR-0003）：任何来源的建议都以「估计代价下降」为实测提升的必要条件；
  冗余候选（确定性判定已覆盖）不浪费影子实证，直接标「未验证（冗余）」；
- EXPLAIN ANALYZE 会真实执行语句：只对 SELECT 取实测耗时参考，DML 绝不执行；
- 单候选环境失败不中断管线（标「未验证（环境原因）」），整体退出码不受 AI 影响。
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime

import pymysql
import pymysql.connections

from modou.optimize.advisor import AdvisorConfig, build_schema_summary, maybe_fetch_candidates
from modou.optimize.candidates import (
    MAX_CANDIDATES_PER_STATEMENT,
    IndexCandidate,
    StatementAnalysis,
    StatementTypeError,
    analyze_statement,
    build_index_ddl,
    index_name_for_candidate,
)
from modou.optimize.explain import (
    explain_analyze_tree,
    explain_json,
    parse_explain_tree_actual_ms,
    refresh_statistics,
)
from modou.optimize.report import EXIT_ERROR, EXIT_OK, STATUS_MEASURED, STATUS_UNVERIFIED, render_text, report_to_json
from modou.optimize.sideeffects import DEFAULT_INDEX_COUNT_LIMIT, check_candidate_side_effects
from modou.replay import env as replay_env
from modou.replay.container import ContainerRuntimeError, ShadowMySQL
from modou.snapshot.introspect import read_meta
from modou.snapshot.model import Snapshot, TableDef
from modou.snapshot.restore import restore_snapshot

# 报告正文随附的实证口径声明
EVIDENCE_NOTE = (
    "代价为优化器估计（基于采样统计），无官方同值保证；"
    "提升幅度 =（基线代价 − 复测代价）/ 基线代价，影子库与目标库大版本一致"
)


class OptimizeInputError(Exception):
    """optimize 输入错误（快照无采样数据/语句类型不支持等），映射退出码 2。"""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class OptimizeOutcome:
    report: dict

    @property
    def exit_code(self) -> int:
        return int(self.report.get("exit_code", EXIT_ERROR))

    def render(self) -> str:
        return render_text(self.report)

    @property
    def report_json(self) -> dict:
        return report_to_json(self.report)


def judge_improvement(cost_before: float | None, cost_after: float | None) -> tuple[str, str | None, float | None]:
    """代价判定：下降=实测提升；持平/上升/代价不可得=未验证（附原因）。"""
    if cost_before is None or cost_after is None:
        return STATUS_UNVERIFIED, "执行计划代价不可得（EXPLAIN JSON 缺少 query_cost 字段）", None
    if cost_after < cost_before:
        improvement = (cost_before - cost_after) / cost_before * 100.0
        return STATUS_MEASURED, None, round(improvement, 2)
    return STATUS_UNVERIFIED, "代价未降低（复测代价不低于基线）", None


def validate_inputs(
    statements: list[str], baseline: Snapshot, *, default_database: str | None = None
) -> list[StatementAnalysis]:
    """输入校验：非空、版本地板、采样数据在场、语句可解析且类型支持、目标库在快照内。"""
    errors: list[str] = []
    if not statements:
        raise OptimizeInputError(["no statements to optimize"])
    errors.extend(replay_env.unsupported_version_errors(baseline.meta))

    has_sample = any(
        table.sample is not None and table.sample.rows
        for inventory in baseline.databases.values()
        for table in inventory.tables.values()
    )
    if not has_sample:
        errors.append(
            "baseline snapshot has no sampled data (optimize needs row samples for cost comparison); "
            "re-capture with --sample-rows"
        )

    analyses: list[StatementAnalysis] = []
    for position, sql in enumerate(statements, start=1):
        try:
            analysis = analyze_statement(sql, default_database)
        except (StatementTypeError, ValueError) as exc:
            errors.append(f"statement #{position}: {exc}")
            continue
        if analysis.database is None:
            errors.append(
                f"statement #{position}: statement has no qualified database and no --default-database was given"
            )
            continue
        if analysis.database not in baseline.databases:
            errors.append(f"statement #{position}: database {analysis.database!r} is not in the snapshot")
            continue
        for ref_db, ref_table in analysis.referenced_tables:
            inventory = baseline.databases.get(ref_db or analysis.database)
            if inventory is None or ref_table not in inventory.tables:
                errors.append(
                    f"statement #{position}: referenced table {ref_db or analysis.database}.{ref_table} "
                    "is not in the snapshot tables (re-capture including it)"
                )
        if errors:
            continue
        analyses.append(analysis)
    if errors:
        raise OptimizeInputError(errors)
    return analyses


def resolve_candidates(
    candidates: list[IndexCandidate],
    tables_map: dict[str, dict[str, TableDef]],
) -> tuple[list[dict], list[str]]:
    """候选校验与物化：表/列必须真实存在（AI 幻觉防线），产出建议条目。

    返回（建议清单, 丢弃原因清单）。索引候选物化为 DDL；改写候选原样透传。
    """
    suggestions: list[dict] = []
    dropped: list[str] = []
    seen: set[tuple[str | None, str, tuple[str, ...]]] = set()
    for candidate in candidates:
        if candidate.kind == "rewrite":
            suggestions.append(
                {
                    "source": candidate.source,
                    "kind": "rewrite",
                    "content": candidate.sql,
                    "columns": [],
                    "table": "",
                    "database": None,
                    "reason_label": candidate.reason,
                }
            )
            continue
        table = tables_map.get(candidate.database or "", {}).get(candidate.table)
        if table is None:
            dropped.append(
                f"{candidate.source} candidate index on unknown table {candidate.database}.{candidate.table} dropped"
            )
            continue
        known_columns = {col.name for col in table.columns}
        unknown = [col for col in candidate.columns if col not in known_columns]
        if unknown:
            dropped.append(
                f"{candidate.source} candidate index on {candidate.database}.{candidate.table} dropped: "
                f"unknown column(s) {', '.join(unknown)}"
            )
            continue
        key = (candidate.database, candidate.table, tuple(candidate.columns))
        if key in seen:
            continue
        seen.add(key)
        columns_meta = {col.name: col for col in table.columns}
        suggestions.append(
            {
                "source": candidate.source,
                "kind": "index",
                "content": build_index_ddl(candidate, columns_meta),
                "columns": list(candidate.columns),
                "table": candidate.table,
                "database": candidate.database,
                "reason_label": candidate.reason,
            }
        )
    return suggestions, dropped


def run_optimize(
    statements: list[str],
    baseline: Snapshot,
    *,
    default_database: str | None = None,
    image: str | None = None,
    container_cli: str | None = None,
    advisor_config: AdvisorConfig | None = None,
    index_count_limit: int = DEFAULT_INDEX_COUNT_LIMIT,
    keep_container: bool = False,
    shadow: ShadowMySQL | None = None,
) -> OptimizeOutcome:
    """执行完整优化实证。容器用后即焚（keep_container=True 保留排查）。

    shadow 参数供测试/复用注入已启动容器：注入时本函数不拉起也不销毁。
    """
    try:
        analyses = validate_inputs(statements, baseline, default_database=default_database)
    except OptimizeInputError as exc:
        return _error_outcome([], input_errors=exc.errors)

    involved_dbs = sorted({analysis.database for analysis in analyses if analysis.database})
    tables_map = {db: baseline.databases[db].tables for db in involved_dbs if db in baseline.databases}

    if shadow is not None:
        return _optimize_on_shadow(
            shadow, baseline, analyses, involved_dbs, tables_map, advisor_config, index_count_limit
        )

    resolved_image = image or f"mysql:{replay_env.version_series(baseline.meta.server_version)}"
    try:
        started = ShadowMySQL.start(resolved_image, cli=container_cli)
    except ContainerRuntimeError as exc:
        return _error_outcome([f"shadow container failed: {exc}"])
    try:
        return _optimize_on_shadow(
            started, baseline, analyses, involved_dbs, tables_map, advisor_config, index_count_limit
        )
    finally:
        if not keep_container:
            with contextlib.suppress(ContainerRuntimeError):
                started.close()


def _optimize_on_shadow(
    shadow: ShadowMySQL,
    baseline: Snapshot,
    analyses: list[StatementAnalysis],
    involved_dbs: list[str],
    tables_map: dict[str, dict[str, TableDef]],
    advisor_config: AdvisorConfig | None,
    index_count_limit: int,
) -> OptimizeOutcome:
    try:
        return _optimize_on_shadow_inner(
            shadow, baseline, analyses, involved_dbs, tables_map, advisor_config, index_count_limit
        )
    except (pymysql.err.MySQLError, OSError, RuntimeError, ValueError) as exc:
        # 影子阶段意外收敛为退出码 2（编程错误类异常不在此网内，保持响亮）
        return _error_outcome([f"shadow operation failed: {exc}"])


def _optimize_on_shadow_inner(
    shadow: ShadowMySQL,
    baseline: Snapshot,
    analyses: list[StatementAnalysis],
    involved_dbs: list[str],
    tables_map: dict[str, dict[str, TableDef]],
    advisor_config: AdvisorConfig | None,
    index_count_limit: int,
) -> OptimizeOutcome:
    conn = shadow.connect_params().connect()
    try:
        shadow_meta = read_meta(conn)
        compat_errors = replay_env.compatibility_errors(baseline.meta, shadow_meta)
        if compat_errors:
            return _error_outcome(compat_errors)
        _set_session_sql_mode(conn, baseline.meta.sql_mode)
        restore_snapshot(conn, baseline, database_filter=set(involved_dbs), include_data=True)
        refresh_statistics(conn, _sampled_tables(baseline, involved_dbs))

        schema_summary = build_schema_summary(baseline, set(involved_dbs))
        databases_report: dict[str, dict] = {}
        advisor_dropped: list[str] = []
        for position, analysis in enumerate(analyses, start=1):
            db_name = analysis.database or involved_dbs[0]
            conn.select_db(db_name)
            statement_report = _measure_statement(
                conn,
                position,
                analysis,
                tables_map,
                schema_summary,
                advisor_config,
                index_count_limit,
                advisor_dropped,
            )
            databases_report.setdefault(db_name, {"statements": []})["statements"].append(statement_report)

        report = {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "exit_code": EXIT_OK,
            "env_errors": [],
            "input_errors": [],
            "advisor": {
                "configured": advisor_config is not None,
                "model": advisor_config.model if advisor_config else None,
                "dropped": advisor_dropped,
            },
            "evidence_env": {
                "note": EVIDENCE_NOTE,
                "tables": _evidence_tables(baseline, involved_dbs),
            },
            "databases": databases_report,
        }
        return OptimizeOutcome(report=report)
    finally:
        conn.close()


def _measure_statement(
    conn: pymysql.connections.Connection,
    position: int,
    analysis: StatementAnalysis,
    tables_map: dict[str, dict[str, TableDef]],
    schema_summary: list[dict],
    advisor_config: AdvisorConfig | None,
    index_count_limit: int,
    advisor_dropped: list[str],
) -> dict:
    """单语句：基线计划 → 规则候选 + AI 候选 → 逐候选实证 → 两级状态。"""
    sql = analysis.sql
    baseline_plan = explain_json(conn, sql)
    actual_before = _reference_actual_ms(conn, analysis)

    ai_candidates = maybe_fetch_candidates(advisor_config, sql, schema_summary)
    # AI 候选通常不带库限定：归属到当前语句的库（表名校验在 resolve_candidates 中兜底）
    for candidate in ai_candidates:
        if candidate.kind == "index" and candidate.database is None and analysis.database is not None:
            candidate.database = analysis.database
    # AI 索引候选同样受每语句候选上限约束（上限约束的是影子实证成本，来源无关）
    kept_ai: list[IndexCandidate] = []
    ai_index_count = 0
    for candidate in ai_candidates:
        if candidate.kind == "index":
            if ai_index_count >= MAX_CANDIDATES_PER_STATEMENT:
                advisor_dropped.append(
                    f"ai candidate index on {candidate.database}.{candidate.table} dropped: "
                    f"per-statement candidate limit {MAX_CANDIDATES_PER_STATEMENT} reached"
                )
                continue
            ai_index_count += 1
        kept_ai.append(candidate)
    suggestions, dropped = resolve_candidates([*analysis.candidates, *kept_ai], tables_map)
    advisor_dropped.extend(dropped)

    measured = [
        _measure_suggestion(
            conn,
            analysis,
            suggestion,
            tables_map,
            index_count_limit,
            actual_before,
            baseline_plan.query_cost,
            baseline_plan.table_accesses,
        )
        for suggestion in suggestions
    ]

    return {
        "index": position,
        "database": analysis.database,
        "sql": sql,
        "baseline": {
            "cost": baseline_plan.query_cost,
            "tables": baseline_plan.table_accesses,
            "actual_time_ms": actual_before,
        },
        "findings": [{"code": f.code, "message": f.message} for f in analysis.findings],
        "suggestions": measured,
    }


def _measure_suggestion(
    conn: pymysql.connections.Connection,
    analysis: StatementAnalysis,
    suggestion: dict,
    tables_map: dict[str, dict[str, TableDef]],
    index_count_limit: int,
    actual_before: float | None,
    baseline_cost: float | None,
    baseline_rows: list[dict],
) -> dict:
    """单候选：副作用检查 → 实证（或确定性跳过）→ 两级状态判定。"""
    result: dict = {
        "source": suggestion["source"],
        "kind": suggestion["kind"],
        "content": suggestion["content"],
        "cost_before": baseline_cost,
        "cost_after": None,
        "improvement_pct": None,
        "rows_before": baseline_rows,
        "rows_after": [],
        "actual_time_before_ms": actual_before,
        "actual_time_after_ms": None,
        "reason": None,
        "side_effects": [],
    }

    if suggestion["kind"] == "index":
        table = tables_map.get(suggestion["database"] or "", {}).get(suggestion["table"])
        notes = (
            check_candidate_side_effects(suggestion["columns"], table, index_count_limit=index_count_limit)
            if table is not None
            else []
        )
        result["side_effects"] = [{"kind": note.kind, "message": note.message} for note in notes]
        if any(note.kind == "CANDIDATE_REDUNDANT" for note in notes):
            result["status"] = STATUS_UNVERIFIED
            result["reason"] = "冗余候选：被现有索引覆盖（确定性判定），未进入影子实证"
            return result
        return _evidence_index_candidate(conn, analysis, suggestion, result, actual_before)
    return _evidence_rewrite_candidate(conn, suggestion, result)


def _evidence_index_candidate(
    conn: pymysql.connections.Connection,
    analysis: StatementAnalysis,
    suggestion: dict,
    result: dict,
    actual_before: float | None,
) -> dict:
    """索引候选实证：应用 DDL → 刷新统计 → 复测 → 删除回滚 → 再刷新统计。"""
    db_name = suggestion["database"]
    table_name = suggestion["table"]
    index_name = index_name_for_candidate(suggestion["columns"])

    def drop_candidate_index() -> None:
        with conn.cursor() as cursor:
            cursor.execute(
                f"ALTER TABLE `{_escape(db_name)}`.`{_escape(table_name)}` DROP INDEX `{_escape(index_name)}`"
            )
        refresh_statistics(conn, [(db_name, table_name)])

    applied = False
    stage = "apply index"
    try:
        with conn.cursor() as cursor:
            cursor.execute(suggestion["content"])
        applied = True
        stage = "refresh statistics"
        refresh_statistics(conn, [(db_name, table_name)])
        stage = "explain"
        after_plan = explain_json(conn, analysis.sql)
        stage = "drop index"
        drop_candidate_index()
    except (pymysql.err.MySQLError, ValueError) as exc:
        result["status"] = STATUS_UNVERIFIED
        result["reason"] = f"影子实证环境原因（{stage} 阶段）：{exc}"
        if applied:
            # 索引已落地：回滚尽力而为；删除失败必须披露（残留索引会让后续候选基线偏高）
            try:
                drop_candidate_index()
            except (pymysql.err.MySQLError, ValueError) as drop_exc:
                result["side_effects"].append(
                    {
                        "kind": "INDEX_DROP_FAILED",
                        "message": (f"候选索引 {index_name} 未能从影子库删除，后续候选的基线可能偏高：{drop_exc}"),
                    }
                )
        return result

    status, reason, improvement = judge_improvement(result["cost_before"], after_plan.query_cost)
    result.update(
        status=status,
        reason=reason,
        improvement_pct=improvement,
        cost_after=after_plan.query_cost,
        rows_after=after_plan.table_accesses,
        actual_time_after_ms=_reference_actual_ms(conn, analysis) if analysis.is_select else None,
    )
    return result


def _evidence_rewrite_candidate(
    conn: pymysql.connections.Connection,
    suggestion: dict,
    result: dict,
) -> dict:
    """改写候选实证：仅 EXPLAIN（绝不执行改写语句），与基线代价对比。"""
    try:
        after_plan = explain_json(conn, suggestion["content"])
    except (pymysql.err.MySQLError, ValueError) as exc:
        result["status"] = STATUS_UNVERIFIED
        result["reason"] = f"改写语句无法在影子库取得执行计划：{exc}"
        return result
    status, reason, improvement = judge_improvement(result["cost_before"], after_plan.query_cost)
    result.update(
        status=status,
        reason=reason,
        improvement_pct=improvement,
        cost_after=after_plan.query_cost,
        rows_after=after_plan.table_accesses,
    )
    return result


def _reference_actual_ms(conn: pymysql.connections.Connection, analysis: StatementAnalysis) -> float | None:
    """EXPLAIN ANALYZE 实测耗时（参考信息）：仅对 SELECT 执行——DML 会真实生效，
    绝不对 UPDATE/DELETE 跑 ANALYZE（红线：影子库实证不污染自身环境）。"""
    if not analysis.is_select:
        return None
    try:
        return parse_explain_tree_actual_ms(explain_analyze_tree(conn, analysis.sql))
    except (pymysql.err.MySQLError, ValueError):
        return None


def _sampled_tables(baseline: Snapshot, dbs: list[str]) -> list[tuple[str, str]]:
    return [
        (db, table.name)
        for db in dbs
        if db in baseline.databases
        for table in baseline.databases[db].tables.values()
        if table.sample is not None and table.sample.rows
    ]


def _evidence_tables(baseline: Snapshot, dbs: list[str]) -> list[dict]:
    """实证环境数据规模声明：涉及库的全部表都列出——未采样表 sampled_rows=None，
    让「该表没有数据支撑代价对比」在报告里可见，而非静默缺席。"""
    tables: list[dict] = []
    for db in dbs:
        if db not in baseline.databases:
            continue
        for table in baseline.databases[db].tables.values():
            sample = table.sample
            tables.append(
                {
                    "database": db,
                    "table": table.name,
                    "sampled_rows": sample.sampled_rows if sample is not None else None,
                    "estimated_rows": sample.estimated_rows if sample is not None else None,
                }
            )
    return tables


def _set_session_sql_mode(conn: pymysql.connections.Connection, sql_mode: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute("SET SESSION sql_mode = %s", (sql_mode,))


def _escape(identifier: str) -> str:
    return identifier.replace("`", "``")


def _error_outcome(errors: list[str], *, input_errors: list[str] | None = None) -> OptimizeOutcome:
    return OptimizeOutcome(
        report={
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "exit_code": EXIT_ERROR,
            "env_errors": errors,
            "input_errors": input_errors or [],
            "advisor": {"configured": False, "model": None, "dropped": []},
            "evidence_env": {"note": "", "tables": []},
            "databases": {},
        }
    )
