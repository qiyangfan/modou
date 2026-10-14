"""verify 管线守卫单测：版本地板在触容器之前显式拒绝（离线，不拉容器）。"""

from __future__ import annotations

from pathlib import Path

from modou.diff.pipeline import run_verify
from modou.report.render import EXIT_ERROR
from modou.snapshot.model import Snapshot, SnapshotMeta


def _snapshot(server_version: str) -> Snapshot:
    return Snapshot(
        format_version=1,
        tool_version="test",
        captured_at="2026-10-14T00:00:00+00:00",
        meta=SnapshotMeta(
            server_version=server_version,
            version_comment="t",
            character_set_server="utf8mb4",
            collation_server="utf8mb4_0900_ai_ci",
            lower_case_table_names=0,
            sql_mode="",
        ),
    )


def _changeset(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "V01__a.sql").write_text("CREATE TABLE t (id INT);", encoding="utf-8")
    (tmp_path / "manifest.txt").write_text("V01__a.sql\n", encoding="utf-8")
    return tmp_path


def test_verify_rejects_pre_8_baseline_before_container_start(tmp_path: Path) -> None:
    cs = _changeset(tmp_path / "cs")
    outcome = run_verify(_snapshot("5.7.40"), _snapshot("5.7.40"), cs)
    assert outcome.exit_code == EXIT_ERROR
    assert outcome.report.env_errors and "not supported" in outcome.report.env_errors[0]
