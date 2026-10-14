"""verify 验收管线：打包校验 → 影子回放 → 三方 diff → 报告与退出码。

编排顺序（spec「回放推导期望态」「三方 diff 验收结论」）：
1. pack 校验变更集（失败 = 输入错误，退出码 2）；
2. 拉起影子容器，校验版本序列与平台参数（不兼容 = 环境错误，退出码 2）；
3. 灌入基线快照 → 回放变更集 = 期望态（回放失败 = 输入错误，退出码 2，中止）；
4. 内省影子库，与基线/实际两份快照逐库三方 diff；
5. 报告聚合（按库分组），退出码取最严重档。
"""

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
    """verify 输入错误（变更集/快照文件问题），映射退出码 2。"""

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
    """执行完整验收。容器用后即焚（keep_container=True 保留以便排查）。

    shadow 参数供测试/复用场景注入已启动的容器：注入时本函数不拉起也不销毁。
    """
    try:
        # 锁风险注记口径随基线大版本（5.7 无 INSTANT），与影子镜像的版本序列同源推导
        target_major = "5.7" if replay_env.version_series(baseline.meta.server_version).startswith("5.") else "8.0"
        pack = pack_changeset(changeset_dir, allow_legacy_names=allow_legacy_names, target_major=target_major)
    except ChangesetValidationError as exc:
        raise VerifyInputError(exc.errors) from exc

    # 采集/内省依赖 8.0+ 专有元数据（STATISTICS.expression、CHECK_CONSTRAINTS），
    # 更老版本在查询期才报晦涩错误——入口处显式拒绝（5.7 仅 pack 锁风险注记口径）
    version_errors = replay_env.unsupported_version_errors(baseline.meta)
    if version_errors:
        return _outcome(EXIT_ERROR, pack=pack, errors=version_errors)

    requested_dbs = _resolve_database_filter(baseline, after, database_filter)
    # 基线缺库 = 变更集新建库场景：可验收（三方 diff 支持 None 基线），
    # 但若回放后影子中也没有该库，则期望态无从推导，属输入错误（_verify_on_shadow 内判定）。
    baseline_missing = [db for db in requested_dbs if db not in baseline.databases]

    if shadow is not None:
        return _verify_on_shadow(shadow, baseline, after, pack, requested_dbs, default_database, baseline_missing)

    started, failure = _start_shadow(image, baseline, container_cli, pack)
    if failure is not None:
        return failure
    if started is None:  # 与 failure 二选一返回，防御性分支（不依赖 assert，python -O 安全）
        return _outcome(EXIT_ERROR, pack=pack, errors=["shadow container did not start (unknown reason)"])
    try:
        return _verify_on_shadow(started, baseline, after, pack, requested_dbs, default_database, baseline_missing)
    finally:
        if not keep_container:
            with contextlib.suppress(ContainerRuntimeError):
                # 清理失败不得吞掉已产出的验收结论（finally 抛异常会覆盖返回值）；
                # 容器残留可经 podman/docker ps 识别后手动清理
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
        # 影子库阶段的任何意外（灌入失败、依赖不收敛 RuntimeError、库缺失 ValueError、
        # select_db 1049、内省失败等）都属环境/输入错误，必须收敛到退出码 2，
        # 不得以裸异常穿透破坏确定性退出码契约（编程错误类异常不在此网内，保持响亮）
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

        # 会话 sql_mode 与基线对齐：同版本服务器的全局 sql_mode 也可能不同，
        # 不对齐时同一语句在线上与影子行为可能不同，期望态会静默失真
        _set_session_sql_mode(conn, baseline.meta.sql_mode)
        restore_snapshot(conn, baseline, database_filter=set(requested_dbs))
    finally:
        conn.close()

    # 回放用全新会话：restore 会把会话库残留在最后一个灌入的库上，
    # 复用会掩盖「未给 --default-database」的错误（未限定语句会静默落进残留库）
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

    # 基线缺库且回放后影子中也没有：期望态无从推导，属输入错误
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
    """内省影子库得到期望态；影子中不存在的库（快照缺失且变更未建）跳过，由管线判定。"""
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
