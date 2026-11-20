"""采集编排的离线用例：用假连接覆盖指令下发与失败收敛，不触真实数据库。"""

from __future__ import annotations

from pathlib import Path

import pytest

from modou.db import MysqlParams
from modou.snapshot import capture as capture_module
from modou.snapshot.capture import capture_to_file
from modou.snapshot.introspect import capture_snapshot
from modou.snapshot.model import DatabaseInventory, Snapshot, SnapshotMeta

META_ROW = ("8.4.6", "MySQL Community Server - GPL", "utf8mb4", "utf8mb4_0900_ai_ci", 0, "")


class _Cursor:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self._row = row

    def execute(self, *_args: object) -> None:
        return None

    def fetchone(self) -> tuple[object, ...] | None:
        return self._row

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class _FakeConnection:
    """最小 pymysql 连接替身：只回一条元信息行并记录关闭。"""

    def __init__(self, row: tuple[object, ...] | None = META_ROW) -> None:
        self._row = row
        self.closed = False

    def cursor(self) -> _Cursor:
        return _Cursor(self._row)

    def close(self) -> None:
        self.closed = True


def _meta() -> SnapshotMeta:
    return SnapshotMeta("8.4.6", "MySQL", "utf8mb4", "utf8mb4_0900_ai_ci", 0, "")


def _params(monkeypatch: pytest.MonkeyPatch, conn: _FakeConnection) -> MysqlParams:
    monkeypatch.setattr(MysqlParams, "connect", lambda self, **_kwargs: conn)
    return MysqlParams(host="127.0.0.1", port=3306, user="u", password="p")


class TestCaptureToFile:
    def test_writes_snapshot_json_and_returns_it(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """采集结果写入文件且与返回值一致；连接必须关闭。"""
        conn = _FakeConnection()
        expected = Snapshot(
            format_version=2,
            tool_version="t",
            captured_at="c",
            meta=_meta(),
            databases={"shop": DatabaseInventory(name="shop", charset="utf8mb4", collation="")},
        )
        seen: dict[str, object] = {}

        def fake_capture(params: MysqlParams, names: list[str], *, sample_rows: int | None = None) -> Snapshot:
            seen.update(params=params, names=names, sample_rows=sample_rows)
            return expected

        monkeypatch.setattr(capture_module, "capture_snapshot", fake_capture)
        out = tmp_path / "snap.json"
        result = capture_to_file(_params(monkeypatch, conn), ["shop"], out, sample_rows=10)

        assert result is expected
        assert seen == {"params": seen["params"], "names": ["shop"], "sample_rows": 10}
        assert out.read_text(encoding="utf-8").strip().startswith("{")


class TestCaptureSnapshotFailures:
    def test_meta_query_without_row_fails_and_closes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """元信息查询无行属于环境错误，必须抛出且释放连接。"""
        conn = _FakeConnection(row=None)

        with pytest.raises(RuntimeError, match="no row"):
            capture_snapshot(_params(monkeypatch, conn), ["shop"])
        assert conn.closed
