"""MCP 表面：与 CLI 分析类子命令 1:1 映射的薄封装（ADR-0002）。

红线落地：
- 零业务逻辑：工具函数只做「参数收窄 → 内核调用 → 结果/错误翻译」，任何业务
  逻辑落在内核库；
- 仅本地 stdio：客户端按需拉起子进程，无端口监听、无常驻、无鉴权；
- 描述与 CLI help 同源（surface_map 提供映射与文案，parity 测试守护漂移）；
- 内核异常翻译为英文工具错误，mask_error_details 遮蔽其余异常细节（防堆栈与
  内部路径泄漏）。

依赖为可选 extra（fastmcp）：未安装时 `modou mcp` 在 CLI 侧报安装指引（退出码 2）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from modou import __version__
from modou.ai.client import config_from_env
from modou.changeset.pack import ChangesetValidationError, pack_changeset
from modou.diff.pipeline import VerifyInputError, run_verify
from modou.optimize.pipeline import run_optimize
from modou.params import PasswordUnavailableError, resolve_params
from modou.replay.splitter import split_statements
from modou.report.opinions import AiOpinion
from modou.server.surface_map import EVIDENCE_PRIMITIVES, EXCLUDED_COMMANDS, cli_command_map
from modou.snapshot.capture import capture_to_file
from modou.snapshot.model import snapshot_from_json


def build_mcp_server() -> FastMCP:
    """构建 MCP server：工具清单与 CLI 分析类子命令一一对应。"""
    mcp = FastMCP(
        "modou",
        version=__version__,
        instructions=(
            "墨斗（modou）：database engineering toolbelt — changeset packing/verification, "
            "slow SQL optimization with shadow-DB evidence, rule lint and drift patrol. "
            "All tools run locally; verification/optimization spin up a disposable containerized "
            "shadow MySQL. exit_code semantics mirror the CLI: 0=ok, 1=findings exist (verify/lint), "
            "2=environment or input error."
        ),
        mask_error_details=True,
    )
    _register_tools(mcp)
    return mcp


def _register_tools(mcp: FastMCP) -> None:
    # 工具参数默认值在定义期求值：常量须在工具定义前绑定（不能放函数体内局部导入）
    from modou.patrol.unused_indexes import DEFAULT_OBSERVE_DAYS

    command_help = cli_command_map()

    @mcp.tool(
        name="pack",
        description=command_help["pack"],
    )
    def pack(
        changeset_dir: str,
        output: str | None = None,
        allow_legacy_names: bool = False,
        target_major: str = "8.0",
    ) -> dict[str, Any]:
        """Merge the changeset in sequence and attach destructive/lock-risk warnings."""
        try:
            result = pack_changeset(
                Path(changeset_dir), allow_legacy_names=allow_legacy_names, target_major=target_major
            )
        except ChangesetValidationError as exc:
            raise ToolError(f"changeset validation failed: {'; '.join(exc.errors)}") from exc
        except ValueError as exc:
            raise ToolError(f"pack failed: {exc}") from exc
        warnings_payload = [
            {
                "source_file": w.source_file,
                "statement_index": w.statement_index,
                "kind": w.kind,
                "level": w.level,
                "message": w.message,
            }
            for w in result.warnings
        ]
        packed_written_to = None
        if output is not None:
            try:
                Path(output).write_text(result.packed_sql, encoding="utf-8")
            except OSError as exc:
                raise ToolError(f"cannot write packed file: {exc}") from exc
            packed_written_to = output
        return {
            "exit_code": 0,
            "packed_sql": None if output is not None else result.packed_sql,
            "packed_written_to": packed_written_to,
            "warnings": warnings_payload,
        }

    @mcp.tool(
        name="verify",
        description=command_help["verify"],
    )
    def verify(
        changeset_dir: str,
        baseline: str,
        after: str,
        default_database: str | None = None,
        database: list[str] | None = None,
        image: str | None = None,
        container_cli: str | None = None,
        allow_legacy_names: bool = False,
        keep_container: bool = False,
    ) -> dict[str, Any]:
        """Replay the changeset on a local shadow MySQL and three-way diff baseline/expected/actual."""
        try:
            baseline_snapshot = snapshot_from_json(Path(baseline).read_text(encoding="utf-8"))
            after_snapshot = snapshot_from_json(Path(after).read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ToolError(f"cannot load snapshot files: {exc}") from exc
        try:
            outcome = run_verify(
                baseline_snapshot,
                after_snapshot,
                Path(changeset_dir),
                image=image,
                container_cli=container_cli,
                database_filter=database,
                default_database=default_database,
                allow_legacy_names=allow_legacy_names,
                keep_container=keep_container,
            )
        except VerifyInputError as exc:
            raise ToolError(f"changeset validation failed: {'; '.join(exc.errors)}") from exc
        # AI 失败归因与 CLI 同车道：未配置零网络；观点只进报告（退出码免疫）
        import os

        from modou.report.opinions import attach_ai_opinions

        ai_config = config_from_env(dict(os.environ))
        opinions: list[AiOpinion] = []
        if ai_config is not None:
            from modou.ai.lane_verify import attribute_findings

            opinions = attribute_findings(
                outcome.report_json,
                Path(changeset_dir),
                baseline_snapshot,
                config=ai_config,
                default_database=default_database,
                allow_legacy_names=allow_legacy_names,
            )
        # 结论性输出：报告与退出码是数据（agent 据此判断结论档位），不转工具错误
        return {"exit_code": outcome.exit_code, "report": attach_ai_opinions(outcome.report_json, opinions)}

    @mcp.tool(
        name="snapshot_capture",
        description=command_help["snapshot_capture"],
    )
    def snapshot_capture(
        database: list[str],
        output: str,
        sample_rows: int | None = None,
        dsn: str | None = None,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
    ) -> dict[str, Any]:
        """Capture a read-only structural snapshot of the given databases."""
        try:
            params = resolve_params(dsn, host, port, user, password, allow_prompt=False)
        except PasswordUnavailableError as exc:
            raise ToolError(str(exc)) from exc
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        try:
            snapshot = capture_to_file(params, list(dict.fromkeys(database)), Path(output), sample_rows=sample_rows)
        except (OSError, ValueError) as exc:
            raise ToolError(f"snapshot capture failed: {exc}") from exc
        except Exception as exc:
            raise ToolError(f"snapshot capture failed: {exc}") from exc
        from modou.snapshot.summary import snapshot_summary

        # 证据原语（ADR-0009）：summary 与 CLI --report-json 同源（snapshot_summary 单源）
        return {"exit_code": 0, "output": str(output), "summary": snapshot_summary(snapshot)}

    @mcp.tool(
        name="optimize",
        description=command_help["optimize"],
    )
    def optimize(
        statements_file: str,
        baseline: str,
        default_database: str | None = None,
        image: str | None = None,
        container_cli: str | None = None,
        index_count_limit: int = 10,
        keep_container: bool = False,
    ) -> dict[str, Any]:
        """Analyze slow SQL, propose index/rewrite candidates and verify them on a local shadow MySQL."""
        try:
            baseline_snapshot = snapshot_from_json(Path(baseline).read_text(encoding="utf-8"))
            statements = split_statements(Path(statements_file).read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
            raise ToolError(f"cannot load inputs: {exc}") from exc
        import os

        outcome = run_optimize(
            statements,
            baseline_snapshot,
            default_database=default_database,
            image=image,
            container_cli=container_cli,
            advisor_config=config_from_env(dict(os.environ)),
            index_count_limit=index_count_limit,
            keep_container=keep_container,
        )
        return {"exit_code": outcome.exit_code, "report": outcome.report_json}

    @mcp.tool(
        name="lint",
        description=command_help["lint"],
    )
    def lint(
        paths: list[str],
        skip_rule: list[str] | None = None,
        config: str | None = None,
    ) -> dict[str, Any]:
        """Run static SQL rule checks (no database). AI residual review when BYOK env is set."""
        import os

        from modou.lint import PARSE_RULE_ID, RULES, lint_paths, result_to_json
        from modou.lint.config import LintConfigError, load_lint_config
        from modou.report.opinions import attach_ai_opinions

        try:
            lint_config = load_lint_config(Path(config) if config else None)
        except LintConfigError as exc:
            raise ToolError(f"lint config error: {exc}") from exc
        disabled = set(lint_config.disabled) | set(skip_rule or [])
        # PARSE.001 是引擎产出的工具命中（非规则清单成员），同属可跳过对象；与 CLI 同语义
        known_rule_ids = {rule.rule_id for rule in RULES} | {PARSE_RULE_ID}
        unknown_rules = sorted(disabled - known_rule_ids)
        if unknown_rules:
            # 与 CLI 同语义：拼错的规则 id 必须拒绝，静默并入会改变审核结论口径
            raise ToolError(f"lint failed: unknown rule id(s) in skip/disable: {', '.join(unknown_rules)}")
        try:
            result = lint_paths([Path(p) for p in paths], RULES, thresholds=lint_config.thresholds, disabled=disabled)
        except (OSError, UnicodeDecodeError) as exc:
            raise ToolError(f"lint failed: {exc}") from exc

        # AI 残留评审与 CLI 同车道：未配置零网络；观点只进报告（退出码免疫）
        ai_config = config_from_env(dict(os.environ))
        opinions: list[AiOpinion] = []
        if ai_config is not None:
            from modou.ai.bundler import StatementUnit
            from modou.ai.lane_lint import review_residual

            units = [StatementUnit(file=r.file, line=r.line, sql=r.sql) for r in result.residuals]
            opinions = review_residual(units, result.hits, ai_config)
        return {"exit_code": result.exit_code, "report": attach_ai_opinions(result_to_json(result), opinions)}

    @mcp.tool(
        name="patrol_drift",
        description=command_help["patrol_drift"],
    )
    def patrol_drift(
        baseline: str,
        after: str | None = None,
        dsn: str | None = None,
        database: list[str] | None = None,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
    ) -> dict[str, Any]:
        """Two-way structural drift between a baseline snapshot and a current snapshot."""
        from modou.patrol.drift import drift_between_snapshots
        from modou.patrol.report import drift_to_json
        from modou.snapshot.introspect import capture_snapshot

        try:
            baseline_snapshot = snapshot_from_json(Path(baseline).read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ToolError(f"cannot load baseline snapshot: {exc}") from exc
        if after is not None:
            try:
                current_snapshot = snapshot_from_json(Path(after).read_text(encoding="utf-8"))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise ToolError(f"cannot load current snapshot: {exc}") from exc
        elif dsn is not None:
            if not database:
                raise ToolError("--database is required with --dsn")
            try:
                params = resolve_params(dsn, host, port, user, password, allow_prompt=False)
                current_snapshot = capture_snapshot(params, list(dict.fromkeys(database)))
            except (PasswordUnavailableError, ValueError) as exc:
                raise ToolError(str(exc)) from exc
            except Exception as exc:
                raise ToolError(f"live capture failed: {exc}") from exc
        else:
            raise ToolError("provide after snapshot path or dsn for live capture")
        report = drift_between_snapshots(baseline_snapshot.databases, current_snapshot.databases)
        return {"exit_code": report.exit_code, "report": drift_to_json(report)}

    @mcp.tool(
        name="patrol_unused_indexes",
        description=command_help["patrol_unused_indexes"],
    )
    def patrol_unused_indexes(
        dsn: str | None = None,
        database: list[str] | None = None,
        snapshot: str | None = None,
        observe_days: int = DEFAULT_OBSERVE_DAYS,
        host: str | None = None,
        port: int | None = None,
        user: str | None = None,
        password: str | None = None,
    ) -> dict[str, Any]:
        """Layered unused-index detection (live) plus offline redundancy judgment (snapshot)."""
        from modou.patrol.report import unused_to_json
        from modou.patrol.unused_indexes import (
            PerformanceSchemaDisabledError,
            UnusedIndexesReport,
            collect_from_live,
            find_redundant_from_inventory,
            judge_unused_indexes,
            read_index_io_counts,
        )

        if observe_days < 1:
            # 与 CLI min=1 同语义：0 天观察窗会让「确认未用」判定失去门槛
            raise ToolError("observe_days must be >= 1")

        usages: list = []
        redundancies: list = []
        uptime: int | None = None
        if dsn is not None:
            if not database:
                raise ToolError("database list is required with dsn")
            try:
                params = resolve_params(dsn, host, port, user, password, allow_prompt=False)
                conn = params.connect()
            except (PasswordUnavailableError, ValueError) as exc:
                raise ToolError(str(exc)) from exc
            except Exception as exc:
                # 建连失败（拒连/超时等）必须翻译为工具错误，否则被 mask 成无信息文案
                raise ToolError(f"unused-indexes failed: {exc}") from exc
            try:
                for db_name in dict.fromkeys(database):
                    inventory, db_uptime = collect_from_live(conn, db_name)
                    uptime = db_uptime
                    counts = read_index_io_counts(conn, db_name)
                    usages.extend(
                        judge_unused_indexes(inventory, counts, uptime_seconds=db_uptime, observe_days=observe_days)
                    )
            except PerformanceSchemaDisabledError as exc:
                raise ToolError(str(exc)) from exc
            except Exception as exc:
                raise ToolError(f"unused-indexes failed: {exc}") from exc
            finally:
                conn.close()
        elif snapshot is not None:
            try:
                snapshot_data = snapshot_from_json(Path(snapshot).read_text(encoding="utf-8"))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise ToolError(f"cannot load snapshot: {exc}") from exc
            for inventory in snapshot_data.databases.values():
                redundancies.extend(find_redundant_from_inventory(inventory))
        else:
            raise ToolError("provide dsn (live) or snapshot (offline)")
        report = UnusedIndexesReport(
            uptime_seconds=uptime, observe_days=observe_days, usages=usages, redundancies=redundancies
        )
        return {"exit_code": 0, "report": unused_to_json(report)}

    @mcp.tool(
        name="patrol_slowlog",
        description=command_help["patrol_slowlog"],
    )
    def patrol_slowlog(
        slowlog_file: str,
        top: int = 20,
    ) -> dict[str, Any]:
        """Aggregate a MySQL slow query log by query fingerprint (pt-query-digest semantics)."""
        from modou.patrol.report import slowlog_to_json
        from modou.patrol.slowlog import analyze_slowlog

        try:
            report = analyze_slowlog(
                Path(slowlog_file).read_text(encoding="utf-8", errors="replace"), slowlog_file, top=top
            )
        except OSError as exc:
            raise ToolError(f"cannot read slowlog: {exc}") from exc
        return {"exit_code": 0, "report": slowlog_to_json(report)}

    @mcp.tool(
        name="patrol_summarize",
        description=command_help["patrol_summarize"],
    )
    def patrol_summarize(
        drift: str | None = None,
        unused: str | None = None,
        slowlog: str | None = None,
    ) -> dict[str, Any]:
        """Cross-signal patrol digest from existing reports. AI narrative when BYOK env is set."""
        import os

        from modou.ai.lane_patrol import narrativize
        from modou.patrol.summary import SummaryInputError, summarize_reports
        from modou.report.opinions import attach_ai_opinions

        def _load(path: str | None) -> dict | None:
            if path is None:
                return None
            try:
                return json.loads(Path(path).read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ToolError(f"cannot load patrol report: {exc}") from exc

        try:
            report = summarize_reports(
                _load(drift),
                _load(unused),
                _load(slowlog),
                inputs={"drift": drift, "unused": unused, "slowlog": slowlog},
            )
        except SummaryInputError as exc:
            raise ToolError(f"patrol summarize failed: {exc}") from exc
        ai_config = config_from_env(dict(os.environ))
        opinions: list[AiOpinion] = []
        if ai_config is not None:
            opinions = narrativize(report, config=ai_config)
        return {"exit_code": int(report["exit_code"]), "report": attach_ai_opinions(report, opinions)}

    @mcp.tool(
        name="version",
        description=command_help["version"],
    )
    def version() -> dict[str, Any]:
        """Print the modou version."""
        return {"exit_code": 0, "version": __version__}


def run_server() -> None:
    """以 stdio 传输运行（客户端按需拉起，进程结束即退）。"""
    build_mcp_server().run()


__all__ = ["EVIDENCE_PRIMITIVES", "EXCLUDED_COMMANDS", "build_mcp_server", "cli_command_map", "run_server"]
