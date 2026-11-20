"""验收管线离线用例：用假影子库走完编排，不拉起容器。"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

import pytest

import modou.verify as verify_module
from modou.db import MysqlParams
from modou.replay.container import ContainerRuntimeError, ShadowMySQL
from modou.replay.replay import ReplayError, ReplayResult
from modou.report.render import EXIT_DIFF, EXIT_ERROR, EXIT_OK
from modou.snapshot.model import (
    DatabaseInventory,
    Snapshot,
    SnapshotMeta,
    TableDef,
)
from modou.verify import run_verify


class _Cursor:
    def __init__(self, owner: _FakeConnection) -> None:
        self._owner = owner

    def execute(self, sql: str, params: object = None) -> None:
        self._owner.executed.append((sql, params))

    def fetchone(self) -> tuple[object, ...] | None:
        if self._owner.meta_row is not None and "VERSION()" in self._owner.executed[-1][0]:
            return self._owner.meta_row
        return None

    def fetchall(self) -> list[tuple[object, ...]]:
        return [(name,) for name in self._owner.existing_dbs]

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class _FakeConnection:
    """记录收到的语句；元信息与库清单由用例预置。"""

    def __init__(
        self,
        meta_row: tuple[object, ...] | None = None,
        existing_dbs: set[str] | None = None,
    ) -> None:
        self.meta_row = meta_row
        self.existing_dbs = existing_dbs or set()
        self.executed: list[tuple[str, object]] = []
        self.selected: list[str] = []

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def select_db(self, name: str) -> None:
        self.selected.append(name)

    def close(self) -> None:
        return None


@dataclass
class _FakeShadow:
    conn: _FakeConnection
    closed: int = 0

    def connect_params(self) -> MysqlParams:
        return MysqlParams(host="127.0.0.1", port=1, user="root", password="p")

    def close(self) -> None:
        self.closed += 1


META_ROW = ("8.4.6", "MySQL", "utf8mb4", "utf8mb4_0900_ai_ci", 0, "")


def _meta() -> SnapshotMeta:
    return SnapshotMeta("8.4.6", "MySQL", "utf8mb4", "utf8mb4_0900_ai_ci", 0, "")


def _inventory() -> DatabaseInventory:
    """单表库素材：基线与实际、期望态共用同一形状，避免无意差异。"""
    return DatabaseInventory(
        name="shop",
        charset="utf8mb4",
        collation="utf8mb4_0900_ai_ci",
        tables={
            "orders": TableDef(
                name="orders",
                engine="InnoDB",
                collation="utf8mb4_0900_ai_ci",
                comment="",
                create_options="",
                ddl="CREATE TABLE orders (id int PRIMARY KEY)",
                columns=[],
                indexes=[],
            )
        },
    )


_TABLE_T = TableDef(
    name="t",
    engine="InnoDB",
    collation="utf8mb4_0900_ai_ci",
    comment="",
    create_options="",
    ddl="CREATE TABLE t (id INT)",
    columns=[],
    indexes=[],
)


def _replayed_inventory(_conn: object, _name: str, **_kwargs: object) -> DatabaseInventory:
    """回放后的实际库:changeset 不改结构,仍与基线同形。"""
    return copy.deepcopy(_inventory())


def _snapshot() -> Snapshot:
    return Snapshot(
        format_version=2,
        tool_version="t",
        captured_at="c",
        meta=_meta(),
        databases={"shop": _inventory()},
    )


def _changeset(tmp_path: Path) -> Path:
    (tmp_path / "V01__a.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "manifest.txt").write_text("V01__a.sql\n", encoding="utf-8")
    return tmp_path


@pytest.fixture(autouse=True)
def _fake_shadow_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认禁掉真实容器拉起；需要区分自建/注入的用例再覆盖本桩。"""

    def no_runtime(*_a: object, **_k: object) -> object:
        raise ContainerRuntimeError("no runtime in offline tests")

    monkeypatch.setattr(ShadowMySQL, "start", no_runtime)


@pytest.fixture()
def patched(monkeypatch: pytest.MonkeyPatch):
    """隔离采集与回放：影子与基线结构一致，回放成功；自建影子默认用假实例。"""
    state: dict[str, object] = {}
    state["shadow"] = _FakeShadow(conn=_FakeConnection())
    monkeypatch.setattr(ShadowMySQL, "start", lambda *_a, **_k: state["shadow"])

    def fake_connect(self: MysqlParams, **_kwargs: object) -> _FakeConnection:
        return state["conn"]  # type: ignore[return-value]

    monkeypatch.setattr(MysqlParams, "connect", fake_connect)
    monkeypatch.setattr(verify_module, "read_meta", lambda _conn: _meta())
    monkeypatch.setattr(verify_module, "restore_snapshot", lambda *_a, **_k: None)
    monkeypatch.setattr(
        verify_module,
        "read_database_inventory",
        _replayed_inventory,
    )
    monkeypatch.setattr(
        verify_module, "replay_statements", lambda _conn, _stmts: ReplayResult(executed_count=1, error=None)
    )
    return state


def _set_conn(state: dict[str, object], existing_dbs: set[str] | None = None) -> _FakeConnection:
    conn = _FakeConnection(
        meta_row=META_ROW,
        existing_dbs={"shop"} if existing_dbs is None else existing_dbs,
    )
    state["conn"] = conn
    return conn


class TestRunVerifyGuards:
    def test_container_start_failure_maps_to_exit_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """影子容器拉不起来属环境错误：退出码 2，且错误里带原因。"""

        def boom(*_a: object, **_k: object) -> object:
            raise ContainerRuntimeError("no runtime")

        monkeypatch.setattr(verify_module.ShadowMySQL, "start", boom)
        outcome = run_verify(_snapshot(), _snapshot(), _changeset(tmp_path))
        assert outcome.exit_code == EXIT_ERROR
        assert "shadow container failed: no runtime" in outcome.report.env_errors

    def test_consistent_expected_state_exits_ok(self, tmp_path: Path, patched: dict[str, object]) -> None:
        """期望态与基线和实际一致时退出码 0，并注入默认库。"""
        conn = _set_conn(patched)
        outcome = run_verify(_snapshot(), _snapshot(), _changeset(tmp_path), default_database="shop")
        assert outcome.exit_code == EXIT_OK
        assert conn.selected == ["shop"]
        assert any(sql.startswith("SET SESSION sql_mode") for sql, _ in conn.executed)

    def test_replay_failure_reports_statement_index(
        self, tmp_path: Path, patched: dict[str, object], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """回放失败带语句序号与错误码，缺默认库时附提示。"""
        _set_conn(patched)
        error = ReplayError(statement_index=0, sql="SELECT 1", error_code=1046, error_message="No database")
        monkeypatch.setattr(
            verify_module, "replay_statements", lambda _conn, _stmts: ReplayResult(executed_count=0, error=error)
        )
        outcome = run_verify(_snapshot(), _snapshot(), _changeset(tmp_path))
        assert outcome.exit_code == EXIT_ERROR
        assert outcome.report.replay_error is not None
        assert "--default-database" in outcome.report.env_errors[0]

    def test_version_mismatch_between_baseline_and_shadow(
        self, tmp_path: Path, patched: dict[str, object], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """影子库版本系列与基线不同即拒绝，避免跨大版本误判。"""
        _set_conn(patched)
        other = SnapshotMeta("5.7.44", "MySQL", "utf8mb4", "utf8mb4_0900_ai_ci", 0, "")
        monkeypatch.setattr(verify_module, "read_meta", lambda _conn: other)
        outcome = run_verify(_snapshot(), _snapshot(), _changeset(tmp_path))
        assert outcome.exit_code == EXIT_ERROR
        assert "version series mismatch" in outcome.report.env_errors[0]

    def test_shadow_operation_error_maps_to_exit_error(
        self, tmp_path: Path, patched: dict[str, object], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """影子阶段运行异常收敛为退出码 2，不冒泡。"""
        _set_conn(patched)

        def explode(*_a: object, **_k: object) -> None:
            raise ValueError("bad snapshot")

        monkeypatch.setattr(verify_module, "restore_snapshot", explode)
        outcome = run_verify(_snapshot(), _snapshot(), _changeset(tmp_path))
        assert outcome.exit_code == EXIT_ERROR
        assert "shadow operation failed: bad snapshot" in outcome.report.env_errors[0]


class TestRunVerifyLifecycle:
    def test_injected_shadow_keeps_lifecycle(self, tmp_path: Path, patched: dict[str, object]) -> None:
        """调用方注入的影子库不由 run_verify 销毁。"""
        _set_conn(patched)
        shadow = _FakeShadow(conn=_FakeConnection())
        outcome = run_verify(_snapshot(), _snapshot(), _changeset(tmp_path), shadow=shadow)  # type: ignore[arg-type]
        assert outcome.exit_code == EXIT_OK
        assert shadow.closed == 0

    def test_self_started_shadow_is_closed(self, tmp_path: Path, patched: dict[str, object], monkeypatch) -> None:
        """自建影子库结束即销毁；keep_container 时保留以便排查。"""
        _set_conn(patched)
        shadow = _FakeShadow(conn=_FakeConnection())
        monkeypatch.setattr(verify_module.ShadowMySQL, "start", lambda *_a, **_k: shadow)
        outcome = run_verify(_snapshot(), _snapshot(), _changeset(tmp_path))
        assert outcome.exit_code == EXIT_OK
        assert shadow.closed == 1

    def test_cleanup_failure_does_not_override_conclusion(
        self, tmp_path: Path, patched: dict[str, object], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """销毁失败不得盖掉已产出的验收结论。"""
        _set_conn(patched)

        def broken_close(self: _FakeShadow) -> None:
            raise ContainerRuntimeError("rm failed")

        monkeypatch.setattr(verify_module.ShadowMySQL, "start", lambda *_a, **_k: _FakeShadow(_FakeConnection()))
        monkeypatch.setattr(_FakeShadow, "close", broken_close)
        outcome = run_verify(_snapshot(), _snapshot(), _changeset(tmp_path))
        assert outcome.exit_code == EXIT_OK


def test_diff_conclusion_sets_exit_diff(tmp_path: Path, patched: dict[str, object], monkeypatch) -> None:
    """三方 diff 有结论时退出码 1，并按库归组。"""
    _set_conn(patched)
    from modou.diff.threeway import ObjectConclusion

    conclusion = ObjectConclusion(
        database="shop", object_type="table", object_name="orders", kind="missing_execution", dimensions=["existence"]
    )
    monkeypatch.setattr(verify_module, "three_way_diff", lambda *_a, **_k: [conclusion])
    outcome = run_verify(_snapshot(), _snapshot(), _changeset(tmp_path))
    assert outcome.exit_code == EXIT_DIFF
    assert list(outcome.report.databases) == ["shop"]
