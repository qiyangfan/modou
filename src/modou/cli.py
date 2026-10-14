"""CLI 入口：子命令按车道落位（snapshot/pack/verify 已上线，optimize/lint/patrol 后续）。

表面层只做参数解析与展示；全部业务逻辑在内核库（ADR-0002）。
CLI 参数/错误文本用英文；报告正文（人读）由 report 模块渲染为中文。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import unquote, urlparse

import pymysql.err
import typer

from modou import __version__
from modou.changeset.pack import ChangesetValidationError, pack_changeset
from modou.db import MysqlParams
from modou.diff.pipeline import VerifyInputError, run_verify
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
    """输出版本号。"""
    typer.echo(f"modou {__version__}")


# ── 快照车道 ─────────────────────────────────────────────────────────────

snapshot_app = typer.Typer(help="快照采集：只读导出线上结构（执行前后各一次）。")
app.add_typer(snapshot_app, name="snapshot")


@snapshot_app.command("capture")
def snapshot_capture(
    database: list[str] = typer.Option(..., "--database", "-d", help="Database names to capture (repeatable)."),
    output: Path = typer.Option(..., "--output", "-o", help="Output JSON file path."),
    dsn: str | None = typer.Option(None, "--dsn", help="Connection DSN: mysql://user:pass@host:port"),
    host: str | None = typer.Option(None, "--host", help="MySQL host (overrides DSN)."),
    port: int | None = typer.Option(None, "--port", min=1, max=65535, help="MySQL port (overrides DSN)."),
    user: str | None = typer.Option(None, "--user", help="MySQL user (overrides DSN)."),
    password: str | None = typer.Option(None, "--password", help="MySQL password (env: MOUDO_MYSQL_PASSWORD)."),
) -> None:
    """Capture a read-only structural snapshot of the given databases."""
    params = _resolve_params(dsn, host, port, user, password)
    try:
        snapshot = capture_to_file(params, list(dict.fromkeys(database)), output)
    except (pymysql.err.MySQLError, ValueError, OSError) as exc:
        # 采集失败均属环境/输入错误（连接、权限、库不存在、版本地板、输出不可写），
        # 契约映射退出码 2；1 保留给「存在差异」语义，采集不产出差异结论
        typer.secho(f"snapshot capture failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"captured {len(snapshot.databases)} database(s) (server {snapshot.meta.server_version}) -> {output}")
    for db_name, inventory in snapshot.databases.items():
        typer.echo(
            f"  {db_name}: {len(inventory.tables)} tables, {len(inventory.views)} views, "
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
    """Replay the changeset on a local shadow MySQL and three-way diff baseline/expected/actual."""
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

    if report_json is not None:
        try:
            report_json.write_text(
                json.dumps(outcome.report_json, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            # 报告不可写属环境错误（契约 2），不得让裸 traceback 覆盖验收结论
            typer.secho(f"cannot write report: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2) from exc
        typer.echo(f"report -> {report_json}", err=True)
    typer.echo(outcome.render())
    raise typer.Exit(code=outcome.exit_code)


def _resolve_params(
    dsn: str | None,
    host: str | None,
    port: int | None,
    user: str | None,
    password: str | None,
) -> MysqlParams:
    """连接参数归一：DSN 为底，显式 flag 覆盖；口令缺省走环境变量与交互提示。"""
    dsn_host, dsn_port, dsn_user, dsn_password = "127.0.0.1", 3306, "root", None
    if dsn is not None:
        parsed = urlparse(dsn if "://" in dsn else f"mysql://{dsn}")
        if parsed.scheme not in ("mysql", ""):
            raise typer.BadParameter(f"unsupported DSN scheme: {parsed.scheme} (expected mysql://)")
        dsn_host = parsed.hostname or dsn_host
        dsn_port = parsed.port or dsn_port
        dsn_user = unquote(parsed.username) if parsed.username else dsn_user
        # `mysql://user:@host` 的空口令是合法显式配置（MySQL 允许），is None 判别才不丢它
        dsn_password = unquote(parsed.password) if parsed.password is not None else None

    # 口令优先级：--password flag > DSN 内嵌 > MOUDO_MYSQL_PASSWORD > 交互提示。
    # DSN 是本次调用显式给出的复合参数，内嵌口令不得被环境状态静默覆盖
    # （libpq/mysql 客户端同款：显式连接信息 > 环境变量）；env 只兜底「DSN 未内嵌
    # 口令」——口令放 env、脚本写无口令 DSN 的安全用法不受影响。空口令是合法配置。
    env_password = os.environ.get("MOUDO_MYSQL_PASSWORD")
    if password is not None:
        resolved_password = password
    elif dsn_password is not None:
        resolved_password = dsn_password
    elif env_password is not None:
        resolved_password = env_password
    else:
        resolved_password = typer.prompt("MySQL password", hide_input=True)
    return MysqlParams(
        host=host or dsn_host,
        port=port or dsn_port,
        user=user or dsn_user,
        password=resolved_password,
    )


if __name__ == "__main__":
    app()
