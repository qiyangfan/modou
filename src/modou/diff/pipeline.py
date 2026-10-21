"""验收管线：在影子库回放变更集推导期望态，再与基线和实际快照做三方 diff。"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pymysql
from pymysql.connections import Connection

from modou.changeset.pack import ChangesetValidationError, PackResult, pack_changeset
from modou.diff.threeway import ObjectConclusion, three_way_diff
from modou.replay import env as replay_env
from modou.replay.container import ContainerRuntimeError, ShadowMySQL
from modou.replay.replay import ReplayError, replay_statements
from modou.replay.splitter import split_statements
from modou.report.render import EXIT_DIFF, EXIT_ERROR, EXIT_OK, VerifyReport, render_text, report_to_json
from modou.snapshot.introspect import read_database_inventory, read_meta
from modou.snapshot.model import DatabaseInventory, Snapshot
from modou.snapshot.restore import restore_snapshot

# MySQL ER_NO_DB_ERROR：语句未限定目标库且会话无默认库
ER_NO_DB_ERROR = 1046


class VerifyInputError(Exception):
    """verify 输入错误，映射退出码 2。"""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class VerifyOutcome:
    report: VerifyReport
    report_json: dict

    @property
    def exit_code(self) -> int:
        return self.report.exit_code

    def render(self) -> str:
        return render_text(self.report)


def run_verify(
    baseline: Snapshot,
    after: Snapshot,
    changeset_dir: Path,
    *,
    image: str | None = None,
    container_cli: str | None = None,
    database_filter: list[str] | None = None,
    default_database: str | None = None,
    allow_legacy_names: bool = False,
    keep_container: bool = False,
    shadow: ShadowMySQL | None = None,
) -> VerifyOutcome:
    """执行完整验收；默认销毁自建容器，注入的容器不接管生命周期。"""
    try:
        # 锁风险注记跟随基线大版本；5.7 无 INSTANT
        target_major = "5.7" if replay_env.version_series(baseline.meta.server_version).startswith("5.") else "8.0"
        pack = pack_changeset(changeset_dir, allow_legacy_names=allow_legacy_names, target_major=target_major)
    except ChangesetValidationError as exc:
        raise VerifyInputError(exc.errors) from exc

    # 采集/内省依赖 8.0+ 元数据（STATISTICS.expression、CHECK_CONSTRAINTS），
    # 入口处拒绝更老版本；5.7 只用于 pack 的锁风险注记
    version_errors = replay_env.unsupported_version_errors(baseline.meta)
    if version_errors:
        return _outcome(EXIT_ERROR, pack=pack, errors=version_errors)

    requested_dbs = _resolve_database_filter(baseline, after, database_filter)
    # 基线缺库可能是变更集新建库；只有回放后影子中也没有该库时才是输入错误
    baseline_missing = [db for db in requested_dbs if db not in baseline.databases]

    if shadow is not None:
        return _verify_on_shadow(shadow, baseline, after, pack, requested_dbs, default_database, baseline_missing)

    started, failure = _start_shadow(image, baseline, container_cli, pack)
    if failure is not None:
        return failure
    if started is None:  # 与 failure 二选一；不用 assert，python -O 下仍生效
        return _outcome(EXIT_ERROR, pack=pack, errors=["shadow container did not start (unknown reason)"])
    try:
        return _verify_on_shadow(started, baseline, after, pack, requested_dbs, default_database, baseline_missing)
    finally:
        if not keep_container:
            with contextlib.suppress(ContainerRuntimeError):
                # 清理失败不能覆盖已产出的验收结论；残留容器可用 podman/docker ps 查找
                started.close()


def _resolve_database_filter(baseline: Snapshot, after: Snapshot, database_filter: list[str] | None) -> list[str]:
    if database_filter:
        return list(dict.fromkeys(database_filter))
    return sorted(set(baseline.databases) | set(after.databases))


def _start_shadow(
    image: str | None,
    baseline: Snapshot,
    container_cli: str | None,
    pack: PackResult,
) -> tuple[ShadowMySQL | None, VerifyOutcome | None]:
    resolved_image = image or f"mysql:{replay_env.version_series(baseline.meta.server_version)}"
    try:
        return ShadowMySQL.start(resolved_image, cli=container_cli), None
    except ContainerRuntimeError as exc:
        return None, _outcome(EXIT_ERROR, pack=pack, errors=[f"shadow container failed: {exc}"])


def _verify_on_shadow(
    shadow: ShadowMySQL,
    baseline: Snapshot,
    after: Snapshot,
    pack: PackResult,
    requested_dbs: list[str],
    default_database: str | None,
    baseline_missing: list[str],
) -> VerifyOutcome:
    try:
        return _verify_on_shadow_inner(shadow, baseline, after, pack, requested_dbs, default_database, baseline_missing)
    except (pymysql.err.MySQLError, OSError, ValueError, RuntimeError) as exc:
        # 影子库阶段的运行异常收敛为退出码 2；编程错误不捕获
        return _outcome(EXIT_ERROR, pack=pack, errors=[f"shadow operation failed: {exc}"])


def _verify_on_shadow_inner(
    shadow: ShadowMySQL,
    baseline: Snapshot,
    after: Snapshot,
    pack: PackResult,
    requested_dbs: list[str],
    default_database: str | None,
    baseline_missing: list[str],
) -> VerifyOutcome:
    conn = shadow.connect_params().connect()
    try:
        shadow_meta = read_meta(conn)
        compat_errors = replay_env.compatibility_errors(baseline.meta, shadow_meta)
        if compat_errors:
            return _outcome(EXIT_ERROR, pack=pack, errors=compat_errors)

        # 会话 sql_mode 对齐基线，否则同一条语句可能得到不同结果
        _set_session_sql_mode(conn, baseline.meta.sql_mode)
        restore_snapshot(conn, baseline, database_filter=set(requested_dbs))
    finally:
        conn.close()

    # 回放用新会话：restore 会残留当前库，复用会掩盖缺少 --default-database 的错误
    conn = shadow.connect_params().connect()
    try:
        _set_session_sql_mode(conn, baseline.meta.sql_mode)
        if default_database is not None:
            conn.select_db(default_database)
        result = replay_statements(conn, split_statements(pack.packed_sql))
        if result.error is not None:
            return _replay_failed(pack, result.error)
        expected_dbs = _introspect_expected(conn, requested_dbs)
    finally:
        conn.close()

    # 基线缺库且回放后影子中也没有：期望态无法推导
    un_derived = [db for db in baseline_missing if db not in expected_dbs]
    if un_derived:
        return _outcome(
            EXIT_ERROR,
            pack=pack,
            errors=[
                f"database {db!r} is absent from the baseline snapshot and was not created by replaying the "
                "changeset; expected state cannot be derived"
                for db in un_derived
            ],
        )

    databases: dict[str, list[ObjectConclusion]] = {}
    for db_name in requested_dbs:
        conclusions = three_way_diff(
            baseline.databases.get(db_name),
            expected_dbs.get(db_name),
            after.databases.get(db_name),
        )
        if conclusions:
            databases[db_name] = conclusions
    return _outcome(EXIT_DIFF if databases else EXIT_OK, pack=pack, databases=databases)


def _set_session_sql_mode(conn: Connection, sql_mode: str) -> None:
    with conn.cursor() as cursor:
        cursor.execute("SET SESSION sql_mode = %s", (sql_mode,))


def _replay_failed(pack: PackResult, error: ReplayError) -> VerifyOutcome:
    payload = {
        "statement_index": error.statement_index,
        "sql": error.sql,
        "error_code": error.error_code,
        "error_message": error.error_message,
    }
    hint = (
        " (hint: statements without USE/qualified names need --default-database)"
        if error.error_code == ER_NO_DB_ERROR
        else ""
    )
    return _outcome(
        EXIT_ERROR,
        pack=pack,
        replay_error=payload,
        errors=[
            f"changeset replay failed at statement #{error.statement_index}: "
            f"error {error.error_code}: {error.error_message}{hint}"
        ],
    )


def _introspect_expected(conn: Connection, requested_dbs: list[str]) -> dict[str, DatabaseInventory]:
    """内省影子库得到期望态；不存在的库跳过，由管线判定。"""
    with conn.cursor() as cursor:
        cursor.execute("SELECT schema_name FROM information_schema.SCHEMATA")
        existing = {str(row[0]) for row in cursor.fetchall()}
    expected: dict[str, DatabaseInventory] = {}
    for db_name in requested_dbs:
        if db_name in existing:
            expected[db_name] = read_database_inventory(conn, db_name)
    return expected


def _outcome(
    exit_code: int,
    *,
    errors: list[str] | None = None,
    pack: PackResult | None = None,
    replay_error: dict | None = None,
    databases: dict[str, list[ObjectConclusion]] | None = None,
) -> VerifyOutcome:
    report = VerifyReport(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        exit_code=exit_code,
        env_errors=errors or [],
        replay_error=replay_error,
        pack_warnings=pack.warnings if pack else [],
        databases=databases or {},
    )
    return VerifyOutcome(report=report, report_json=report_to_json(report))
