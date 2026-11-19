"""影子库环境兼容检查：版本序列与 lower_case_table_names 必须与基线一致。"""

from __future__ import annotations

from modou.replay.env import compatibility_errors
from modou.snapshot.model import SnapshotMeta


def _meta(server_version: str = "8.0.36", lower_case_table_names: int = 0) -> SnapshotMeta:
    return SnapshotMeta(
        server_version=server_version,
        version_comment="t",
        character_set_server="utf8mb4",
        collation_server="utf8mb4_0900_ai_ci",
        lower_case_table_names=lower_case_table_names,
        sql_mode="",
    )


def test_same_series_and_case_setting_pass() -> None:
    assert compatibility_errors(_meta(), _meta()) == []


def test_series_mismatch_rejected() -> None:
    errors = compatibility_errors(_meta("8.0.36"), _meta("8.4.11"))
    assert len(errors) == 1
    assert "version series mismatch" in errors[0]


def test_lower_case_table_names_mismatch_rejected() -> None:
    errors = compatibility_errors(_meta(), _meta(lower_case_table_names=1))
    assert len(errors) == 1
    assert "lower_case_table_names mismatch" in errors[0]
