"""CLI 入口：子命令按车道落位（snapshot/pack/verify 已上线，optimize/lint/patrol 后续）。

表面层只做参数解析与展示；全部业务逻辑在内核库（ADR-0002）。
CLI 参数/错误文本用英文；报告正文（人读）由 report 模块渲染为中文。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pymysql.err
import typer

from modou import __version__
from modou.ai.client import config_from_env as ai_config_from_env
from modou.changeset.pack import ChangesetValidationError, pack_changeset
from modou.db import MysqlParams
from modou.diff.pipeline import VerifyInputError, run_verify
from modou.lint import PARSE_RULE_ID, RULES, lint_paths
from modou.lint import render_text as render_lint_text
from modou.lint.config import LintConfigError, load_lint_config
from modou.optimize.pipeline import run_optimize
from modou.params import resolve_params
from modou.patrol.unused_indexes import DEFAULT_OBSERVE_DAYS
from modou.replay.splitter import split_statements
from modou.report.opinions import AiOpinion, attach_ai_opinions, render_opinions_section
from modou.snapshot.capture import capture_to_file
from modou.snapshot.model import snapshot_from_json

app = typer.Typer(
    name="modou",
    help="墨斗：数据库工程化的本地层——变更验收、SQL 优化、规则审核、漂移洞察。",
    no_args_is_help=True,
)


# 单命令的 Typer app 会被当作单命令应用（子命令名变成参数），callback 强制子命令模式
@app.callback()
def main() -> None:
    """墨斗：数据库工程化的本地层——变更验收、SQL 优化、规则审核、漂移洞察。"""


@app.command()
def version() -> None:
    """Print the modou version."""
    typer.echo(f"modou {__version__}")


# ── 快照车道 ─────────────────────────────────────────────────────────────

snapshot_app = typer.Typer(help="快照采集：只读导出线上结构（执行前后各一次）。")
app.add_typer(snapshot_app, name="snapshot")


@snapshot_app.command("capture")
def snapshot_capture(
    database: list[str] = typer.Option(..., "--database", "-d", help="Database names to capture (repeatable)."),
    output: Path = typer.Option(..., "--output", "-o", help="Output JSON file path."),
    sample_rows: int | None = typer.Option(
        None,
        "--sample-rows",
        min=1,
        help="Sample N rows per table (primary-key order) for optimize evidence; omit for structure-only.",
    ),
    dsn: str | None = typer.Option(None, "--dsn", help="Connection DSN: mysql://user:pass@host:port"),
    host: str | None = typer.Option(None, "--host", help="MySQL host (overrides DSN)."),
    port: int | None = typer.Option(None, "--port", min=1, max=65535, help="MySQL port (overrides DSN)."),
    user: str | None = typer.Option(None, "--user", help="MySQL user (overrides DSN)."),
    password: str | None = typer.Option(None, "--password", help="MySQL password (env: MOUDO_MYSQL_PASSWORD)."),
    report_json: Path | None = typer.Option(
        None, "--report-json", help="Write metadata-only snapshot summary (evidence primitive for host agents)."
    ),
) -> None:
    """Capture a read-only structural snapshot of the given databases."""
    params = _resolve_params(dsn, host, port, user, password)
    try:
        snapshot = capture_to_file(params, list(dict.fromkeys(database)), output, sample_rows=sample_rows)
    except (pymysql.err.MySQLError, ValueError, OSError) as exc:
        # 采集失败均属环境/输入错误（连接、权限、库不存在、版本地板、输出不可写），
        # 契约映射退出码 2；1 保留给「存在差异」语义，采集不产出差异结论
        typer.secho(f"snapshot capture failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    if report_json is not None:
        from modou.snapshot.summary import snapshot_summary

        try:
            report_json.write_text(
                json.dumps(snapshot_summary(snapshot), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            typer.secho(f"cannot write report: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(f"report -> {report_json}", err=True)
    sampled_note = f", sample-rows={sample_rows}" if sample_rows else ""
    typer.echo(
        f"captured {len(snapshot.databases)} database(s) "
        f"(server {snapshot.meta.server_version}{sampled_note}) -> {output}"
    )
    for db_name, inventory in snapshot.databases.items():
        sampled = sum(1 for t in inventory.tables.values() if t.sample is not None and t.sample.rows)
        typer.echo(
            f"  {db_name}: {len(inventory.tables)} tables ({sampled} sampled), {len(inventory.views)} views, "
            f"{len(inventory.procedures)} procedures, {len(inventory.functions)} functions, "
            f"{len(inventory.triggers)} triggers, {len(inventory.events)} events"
        )


# ── 变更车道：pack ───────────────────────────────────────────────────────


@app.command()
def pack(
    changeset_dir: Path = typer.Argument(..., help="Changeset directory (V<seq>__<desc>.sql + manifest.txt)."),
    output: Path | None = typer.Option(None, "--output", "-o", help="Write merged SQL to file (default: stdout)."),
    report_json: Path | None = typer.Option(None, "--report-json", help="Write machine-readable warnings to file."),
    allow_legacy_names: bool = typer.Option(
        False, "--allow-legacy-names", help="Admit non-V-named .sql files (legacy directory)."
    ),
    target_major: str = typer.Option(
        "8.0", "--target-major", help="Target MySQL major for lock-risk notes (5.7 or 8.0)."
    ),
) -> None:
    """Merge the changeset in sequence and attach destructive/lock-risk warnings."""
    try:
        result = pack_changeset(
            changeset_dir,
            allow_legacy_names=allow_legacy_names,
            target_major=target_major,
        )
    except ChangesetValidationError as exc:
        typer.secho("changeset validation failed, packing rejected:", fg=typer.colors.RED, err=True)
        for error in exc.errors:
            typer.secho(f"  - {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
    except ValueError as exc:
        # 参数取值错误（如 --target-major 不在支持清单）收敛为退出码 2，不裸穿 traceback
        typer.secho(f"pack failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    if output is None:
        typer.echo(result.packed_sql, nl=False)
    else:
        try:
            output.write_text(result.packed_sql, encoding="utf-8")
        except OSError as exc:
            typer.secho(f"cannot write packed file: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from exc
        discovery = result.discovery
        if discovery is not None:  # 不用 assert：python -O 会剥离断言（仓库约定）
            typer.echo(f"packed {len(discovery.items)} file(s) -> {output}", err=True)

    # 预警是诊断信息，一律走 stderr：产物走 stdout 重定向（缺省 --output 即 stdout）时
    # 交付给运维的合并脚本不得混入非 SQL 文本
    for warning in result.warnings:
        typer.secho(
            f"[{warning.kind}] {warning.source_file} #{warning.statement_index}: {warning.message}",
            fg=typer.colors.YELLOW,
            err=True,
        )
    if report_json is not None:
        try:
            report_json.write_text(
                json.dumps(
                    [
                        {
                            "source_file": w.source_file,
                            "statement_index": w.statement_index,
                            "kind": w.kind,
                            "level": w.level,
                            "message": w.message,
                        }
                        for w in result.warnings
                    ],
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            typer.secho(f"cannot write warnings report: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(f"warnings report -> {report_json}", err=True)


# ── 变更车道：verify ─────────────────────────────────────────────────────


@app.command()
def verify(
    changeset_dir: Path = typer.Argument(..., help="Changeset directory (V<seq>__<desc>.sql + manifest.txt)."),
    baseline: Path = typer.Option(..., "--baseline", help="Before-execution snapshot JSON."),
    after: Path = typer.Option(..., "--after", help="After-execution snapshot JSON."),
    image: str | None = typer.Option(None, "--image", help="Shadow image (default: mysql:<baseline version series>)."),
    container_cli: str | None = typer.Option(
        None, "--container-cli", help="Container CLI (podman/docker; auto-detect)."
    ),
    database: list[str] | None = typer.Option(
        None, "--database", "-d", help="Databases to verify (default: all in snapshots)."
    ),
    default_database: str | None = typer.Option(
        None, "--default-database", help="Default database for statements without USE/qualification."
    ),
    report_json: Path | None = typer.Option(None, "--report-json", help="Write machine-readable report to file."),
    allow_legacy_names: bool = typer.Option(
        False, "--allow-legacy-names", help="Admit non-V-named .sql files (legacy directory)."
    ),
    keep_container: bool = typer.Option(
        False, "--keep-container", help="Keep the shadow container for troubleshooting."
    ),
) -> None:
    """Replay the changeset on a local shadow MySQL and three-way diff baseline/expected/actual.

    Optional AI failure attribution: set MOUDO_AI_BASE_URL / MOUDO_AI_API_KEY / MOUDO_AI_MODEL (BYOK).
    Without configuration no network request is made; opinions never affect the exit code.
    """
    try:
        baseline_snapshot = snapshot_from_json(baseline.read_text(encoding="utf-8"))
        after_snapshot = snapshot_from_json(after.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        typer.secho(f"cannot load snapshot files: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    try:
        outcome = run_verify(
            baseline_snapshot,
            after_snapshot,
            changeset_dir,
            image=image,
            container_cli=container_cli,
            database_filter=list(database) if database else None,
            default_database=default_database,
            allow_legacy_names=allow_legacy_names,
            keep_container=keep_container,
        )
    except VerifyInputError as exc:
        typer.secho("changeset validation failed:", fg=typer.colors.RED, err=True)
        for error in exc.errors:
            typer.secho(f"  - {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    # AI 失败归因（可选）：零差异零调用；观点只进报告单列区（退出码免疫）
    ai_config = ai_config_from_env(dict(os.environ))
    opinions: list[AiOpinion] = []
    if ai_config is not None:
        from modou.ai.lane_verify import attribute_findings

        opinions = attribute_findings(
            outcome.report_json,
            changeset_dir,
            baseline_snapshot,
            config=ai_config,
            default_database=default_database,
            allow_legacy_names=allow_legacy_names,
        )

    if report_json is not None:
        try:
            report_json.write_text(
                json.dumps(attach_ai_opinions(outcome.report_json, opinions), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            # 报告不可写属环境错误（契约 2），不得让裸 traceback 覆盖验收结论
            typer.secho(f"cannot write report: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(f"report -> {report_json}", err=True)
    typer.echo(outcome.render() + render_opinions_section(opinions))
    raise typer.Exit(code=outcome.exit_code)


# ── 优化车道：optimize ───────────────────────────────────────────────────


@app.command()
def optimize(
    statements_file: Path = typer.Argument(..., help="File with slow SQL statement(s) (SELECT/UPDATE/DELETE)."),
    baseline: Path = typer.Option(
        ..., "--baseline", help="Sampled baseline snapshot JSON (see snapshot capture --sample-rows)."
    ),
    default_database: str | None = typer.Option(
        None, "--default-database", help="Default database for statements without USE/qualification."
    ),
    image: str | None = typer.Option(None, "--image", help="Shadow image (default: mysql:<baseline version series>)."),
    container_cli: str | None = typer.Option(
        None, "--container-cli", help="Container CLI (podman/docker; auto-detect)."
    ),
    report_json: Path | None = typer.Option(None, "--report-json", help="Write machine-readable report to file."),
    index_count_limit: int = typer.Option(
        10, "--index-count-limit", min=1, help="Secondary-index-per-table limit for side-effect warnings."
    ),
    keep_container: bool = typer.Option(
        False, "--keep-container", help="Keep the shadow container for troubleshooting."
    ),
) -> None:
    """Analyze slow SQL, propose index/rewrite candidates and verify them on a local shadow MySQL.

    AI advisor is optional: set MOUDO_AI_BASE_URL / MOUDO_AI_API_KEY / MOUDO_AI_MODEL (BYOK).
    Without configuration no network request is made.
    """
    try:
        baseline_snapshot = snapshot_from_json(baseline.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        typer.secho(f"cannot load baseline snapshot: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    try:
        statements = split_statements(statements_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        typer.secho(f"cannot read statements file: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    advisor_config = ai_config_from_env(dict(os.environ))
    outcome = run_optimize(
        statements,
        baseline_snapshot,
        default_database=default_database,
        image=image,
        container_cli=container_cli,
        advisor_config=advisor_config,
        index_count_limit=index_count_limit,
        keep_container=keep_container,
    )

    if report_json is not None:
        try:
            report_json.write_text(
                json.dumps(outcome.report_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            # 报告不可写属环境错误（契约 2），不得让裸 traceback 覆盖结论
            typer.secho(f"cannot write report: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(f"report -> {report_json}", err=True)
    typer.echo(outcome.render())
    if outcome.exit_code != 0:
        raise typer.Exit(code=outcome.exit_code)


# ── 审核车道：lint ───────────────────────────────────────────────────────


@app.command()
def lint(
    paths: list[Path] = typer.Argument(..., help="SQL file(s), directory or changeset directory."),
    report_json: Path | None = typer.Option(None, "--report-json", help="Write machine-readable hits to file."),
    skip_rule: list[str] = typer.Option([], "--skip-rule", help="Skip a rule id (repeatable; overrides config file)."),
    config: Path | None = typer.Option(None, "--config", help="Config file (default: modou.toml in cwd)."),
) -> None:
    """Run static SQL rule checks (no database). Exit 0/1/2.

    Optional AI residual review: set MOUDO_AI_BASE_URL / MOUDO_AI_API_KEY / MOUDO_AI_MODEL (BYOK).
    Without configuration no network request is made and the report carries no AI section.
    """
    try:
        lint_config = load_lint_config(config)
    except LintConfigError as exc:
        typer.secho(f"lint config error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    disabled = set(lint_config.disabled) | set(skip_rule)
    # PARSE.001 是引擎产出的工具命中（非规则清单成员），同属可跳过对象
    known_rule_ids = {rule.rule_id for rule in RULES} | {PARSE_RULE_ID}
    missing_rules = sorted(disabled - known_rule_ids)
    if missing_rules:
        typer.secho(
            f"unknown rule id(s) in skip/disable: {', '.join(missing_rules)}",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)
    for path in paths:
        if not path.exists():
            typer.secho(f"path not found: {path}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2)
    try:
        result = lint_paths(list(paths), RULES, thresholds=lint_config.thresholds, disabled=disabled)
    except (OSError, UnicodeDecodeError) as exc:
        typer.secho(f"lint failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    # AI 残留评审（可选）：引擎单趟产出的残留面交内置通道出观点；未配置零网络，
    # 观点只进报告单列区（退出码免疫，opinions 契约模块单源）
    ai_config = ai_config_from_env(dict(os.environ))
    opinions: list[AiOpinion] = []
    if ai_config is not None:
        from modou.ai.bundler import StatementUnit
        from modou.ai.lane_lint import review_residual

        units = [StatementUnit(file=r.file, line=r.line, sql=r.sql) for r in result.residuals]
        opinions = review_residual(units, result.hits, ai_config)

    if report_json is not None:
        from modou.lint import result_to_json

        try:
            report_json.write_text(
                json.dumps(attach_ai_opinions(result_to_json(result), opinions), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            typer.secho(f"cannot write report: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(f"report -> {report_json}", err=True)
    typer.echo(render_lint_text(result) + render_opinions_section(opinions))
    raise typer.Exit(code=result.exit_code)


# ── 洞察车道：patrol ─────────────────────────────────────────────────────

patrol_app = typer.Typer(help="漂移巡检：两方漂移 / 未用与冗余索引 / 慢日志指纹聚合。")
app.add_typer(patrol_app, name="patrol")


@patrol_app.command("drift")
def patrol_drift(
    baseline: Path = typer.Option(..., "--baseline", help="Baseline snapshot JSON."),
    after: Path | None = typer.Option(None, "--after", help="Current snapshot JSON (or use --dsn to capture live)."),
    dsn: str | None = typer.Option(None, "--dsn", help="Capture the current snapshot live from this DSN."),
    database: list[str] = typer.Option([], "--database", "-d", help="Databases to patrol (repeatable)."),
    host: str | None = typer.Option(None, "--host"),
    port: int | None = typer.Option(None, "--port", min=1, max=65535),
    user: str | None = typer.Option(None, "--user"),
    password: str | None = typer.Option(None, "--password", help="MySQL password (env: MOUDO_MYSQL_PASSWORD)."),
    report_json: Path | None = typer.Option(None, "--report-json"),
) -> None:
    """Two-way structural drift between a baseline snapshot and a current snapshot."""
    try:
        baseline_snapshot = snapshot_from_json(baseline.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        typer.secho(f"cannot load baseline snapshot: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    if after is not None:
        try:
            current_snapshot = snapshot_from_json(after.read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            typer.secho(f"cannot load current snapshot: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from exc
    elif dsn is not None:
        if not database:
            typer.secho("--database is required with --dsn", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2)
        try:
            params = resolve_params(dsn, host, port, user, password, allow_prompt=True)
            from modou.snapshot.introspect import capture_snapshot

            current_snapshot = capture_snapshot(params, list(dict.fromkeys(database)))
        except (pymysql.err.MySQLError, OSError, ValueError) as exc:
            typer.secho(f"live capture failed: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from exc
    else:
        typer.secho("provide --after snapshot or --dsn for live capture", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    from modou.patrol.drift import drift_between_snapshots
    from modou.patrol.report import drift_render, drift_to_json, dumps

    report = drift_between_snapshots(baseline_snapshot.databases, current_snapshot.databases)
    if report_json is not None:
        try:
            report_json.write_text(dumps(drift_to_json(report)), encoding="utf-8")
        except OSError as exc:
            typer.secho(f"cannot write report: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(f"report -> {report_json}", err=True)
    typer.echo(drift_render(report))
    raise typer.Exit(code=report.exit_code)


@patrol_app.command("unused-indexes")
def patrol_unused_indexes(
    dsn: str | None = typer.Option(None, "--dsn", help="Live mode: DSN of the target server."),
    database: list[str] = typer.Option([], "--database", "-d", help="Databases (repeatable; live mode)."),
    snapshot: Path | None = typer.Option(None, "--snapshot", help="Offline mode: snapshot JSON for redundancy checks."),
    observe_days: int = typer.Option(
        DEFAULT_OBSERVE_DAYS, "--observe-days", min=1, help="Observation window in days for confirmed-unused."
    ),
    host: str | None = typer.Option(None, "--host"),
    port: int | None = typer.Option(None, "--port", min=1, max=65535),
    user: str | None = typer.Option(None, "--user"),
    password: str | None = typer.Option(None, "--password", help="MySQL password (env: MOUDO_MYSQL_PASSWORD)."),
    report_json: Path | None = typer.Option(None, "--report-json"),
) -> None:
    """Layered unused-index detection (live) plus offline redundancy judgment (snapshot)."""
    from modou.patrol.report import dumps, unused_render, unused_to_json
    from modou.patrol.unused_indexes import (
        PerformanceSchemaDisabledError,
        UnusedIndexesReport,
        collect_from_live,
        find_redundant_from_inventory,
        judge_unused_indexes,
        read_index_io_counts,
    )

    report_kwargs: dict = {"observe_days": observe_days, "uptime_seconds": None}
    inventories = []

    if dsn is not None:
        if not database:
            typer.secho("--database is required with --dsn", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2)
        try:
            params = resolve_params(dsn, host, port, user, password, allow_prompt=True)
            uptime: int | None = None
            conn = params.connect()
            try:
                for db_name in dict.fromkeys(database):
                    inventory, uptime = collect_from_live(conn, db_name)
                    inventories.append(inventory)
                last_uptime = uptime
            finally:
                conn.close()
        except (pymysql.err.MySQLError, OSError, ValueError, PerformanceSchemaDisabledError) as exc:
            typer.secho(f"unused-indexes failed: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from exc
        report_kwargs["uptime_seconds"] = last_uptime
    elif snapshot is not None:
        try:
            snapshot_data = snapshot_from_json(snapshot.read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            typer.secho(f"cannot load snapshot: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from exc
        inventories.extend(snapshot_data.databases.values())
    else:
        typer.secho("provide --dsn (live) or --snapshot (offline)", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    from modou.patrol.unused_indexes import IndexUsage

    usages: list[IndexUsage] = []
    redundancies = []
    for inventory in inventories:
        if report_kwargs["uptime_seconds"] is not None:
            try:
                conn = params.connect()
                try:
                    counts = read_index_io_counts(conn, inventory.name)
                finally:
                    conn.close()
            except (pymysql.err.MySQLError, PerformanceSchemaDisabledError) as exc:
                typer.secho(f"unused-indexes failed: {exc}", fg=typer.colors.RED, err=True)
                raise typer.Exit(code=2) from exc
            usages.extend(
                judge_unused_indexes(
                    inventory,
                    counts,
                    uptime_seconds=report_kwargs["uptime_seconds"],
                    observe_days=report_kwargs["observe_days"],
                )
            )
        redundancies.extend(find_redundant_from_inventory(inventory))

    report = UnusedIndexesReport(**report_kwargs, usages=usages, redundancies=redundancies)
    if report_json is not None:
        try:
            report_json.write_text(dumps(unused_to_json(report)), encoding="utf-8")
        except OSError as exc:
            typer.secho(f"cannot write report: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(f"report -> {report_json}", err=True)
    typer.echo(unused_render(report))


@patrol_app.command("summarize")
def patrol_summarize(
    drift: Path | None = typer.Option(None, "--drift", help="Drift report JSON (patrol_drift)."),
    unused: Path | None = typer.Option(None, "--unused", help="Unused-indexes report JSON (patrol_unused_indexes)."),
    slowlog: Path | None = typer.Option(None, "--slowlog", help="Slowlog report JSON (patrol_slowlog)."),
    report_json: Path | None = typer.Option(None, "--report-json"),
) -> None:
    """Cross-signal patrol digest from existing reports.

    Optional AI narrative: set MOUDO_AI_BASE_URL / MOUDO_AI_API_KEY / MOUDO_AI_MODEL (BYOK).
    Without configuration no network request is made; opinions never affect the exit code.
    """
    from modou.patrol.summary import SummaryInputError, summarize_render, summarize_reports

    def _load(option: str, path: Path | None) -> dict | None:
        if path is None:
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            typer.secho(f"cannot load {option} report: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from exc

    try:
        report = summarize_reports(
            _load("drift", drift),
            _load("unused", unused),
            _load("slowlog", slowlog),
            inputs={
                "drift": str(drift) if drift else None,
                "unused": str(unused) if unused else None,
                "slowlog": str(slowlog) if slowlog else None,
            },
        )
    except SummaryInputError as exc:
        typer.secho(f"patrol summarize failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc

    # AI 跨信号叙事（可选）：digest 是确定性事实，叙事是观点（退出码免疫）
    ai_config = ai_config_from_env(dict(os.environ))
    opinions: list[AiOpinion] = []
    if ai_config is not None:
        from modou.ai.lane_patrol import narrativize

        opinions = narrativize(report, config=ai_config)

    if report_json is not None:
        try:
            report_json.write_text(
                json.dumps(attach_ai_opinions(report, opinions), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            typer.secho(f"cannot write report: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(f"report -> {report_json}", err=True)
    typer.echo(summarize_render(report) + render_opinions_section(opinions))
    raise typer.Exit(code=int(report["exit_code"]))


@patrol_app.command("slowlog")
def patrol_slowlog(
    slowlog_file: Path = typer.Argument(..., help="Slow query log file (local, parsed offline)."),
    top: int = typer.Option(20, "--top", min=1, help="Top N fingerprints by total query time."),
    report_json: Path | None = typer.Option(None, "--report-json"),
) -> None:
    """Aggregate a MySQL slow query log by query fingerprint (pt-query-digest semantics)."""
    from modou.patrol.report import dumps, slowlog_render, slowlog_to_json
    from modou.patrol.slowlog import analyze_slowlog

    try:
        report = analyze_slowlog(slowlog_file.read_text(encoding="utf-8", errors="replace"), str(slowlog_file), top=top)
    except OSError as exc:
        typer.secho(f"cannot read slowlog: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    if report_json is not None:
        try:
            report_json.write_text(dumps(slowlog_to_json(report)), encoding="utf-8")
        except OSError as exc:
            typer.secho(f"cannot write report: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(f"report -> {report_json}", err=True)
    typer.echo(slowlog_render(report))


# ── MCP 表面 ─────────────────────────────────────────────────────────────


@app.command()
def mcp() -> None:
    """Start the MCP server (stdio, local-only). Requires the 'mcp' extra."""
    try:
        from modou.server import run_server

        run_server()
    except ModuleNotFoundError as exc:
        if exc.name != "fastmcp":
            raise
        typer.secho(
            "MCP surface dependencies not installed (fastmcp missing); "
            "install with: uv tool install 'modou[mcp]' or pip install 'modou[mcp]'",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2) from exc


def _resolve_params(
    dsn: str | None,
    host: str | None,
    port: int | None,
    user: str | None,
    password: str | None,
) -> MysqlParams:
    """连接参数归一（CLI 面）：允许交互提示；实现单源在 modou.params（MCP 同源）。"""
    try:
        return resolve_params(dsn, host, port, user, password, allow_prompt=True)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


# ── 薄报告层：ui ─────────────────────────────────────────────────────────


@app.command()
def ui(
    report: list[Path] = typer.Option(..., "--report", help="Report JSON file(s) (repeatable)."),
    port: int = typer.Option(0, "--port", min=0, max=65535, help="Local port (0 = pick a free one)."),
    bind: str = typer.Option("127.0.0.1", "--bind", help="Bind address (loopback only)."),
    no_open: bool = typer.Option(False, "--no-open", help="Do not open the browser (headless/remote shell)."),
) -> None:
    """Render reports in a local read-only web UI (loopback only, no login)."""
    from modou.ui import ReportLoadError, load_report, run_ui
    from modou.ui.server import UiBindError

    try:
        for path in report:
            load_report(path)  # 先全部过门禁，坏输入不进服务
        server, _reports = run_ui(list(report), port=port, bind=bind, open_browser=not no_open)
    except (ReportLoadError, UiBindError, OSError) as exc:
        # OSError 覆盖端口占用/绑定失败（EADDRINUSE 等）：用户可修正的输入错误，退出码 2
        typer.secho(f"ui failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    import threading

    actual_port = server.server_address[1]
    # 服务地址无条件可见：无头环境浏览器打不开时用户仍能手动访问
    typer.echo(f"serving on http://127.0.0.1:{actual_port} (Ctrl-C to stop)", err=True)
    try:
        # serve_forever 已由 run_ui 以守护线程启动：主线程只等待中断信号
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
    raise typer.Exit(code=0)


if __name__ == "__main__":
    app()
