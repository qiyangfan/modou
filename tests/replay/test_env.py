"""环境兼容检查单测：版本序列推导与采集支持地板（8.0）。"""

from __future__ import annotations

import pytest

from modou.replay.env import unsupported_version_errors, version_series
from modou.snapshot.model import SnapshotMeta


def _meta(server_version: str) -> SnapshotMeta:
    return SnapshotMeta(
        server_version=server_version,
        version_comment="t",
        character_set_server="utf8mb4",
        collation_server="utf8mb4_0900_ai_ci",
        lower_case_table_names=0,
        sql_mode="",
    )


@pytest.mark.parametrize(
    ("server_version", "expected"),
    [("8.4.6", "8.4"), ("8.0.36", "8.0"), ("5.7.40-log", "5.7"), ("9.1.0", "9.1")],
)
def test_version_series(server_version: str, expected: str) -> None:
    assert version_series(server_version) == expected


@pytest.mark.parametrize("server_version", ["8.0.36", "8.4.11", "9.1.0"])
def test_supported_versions_pass(server_version: str) -> None:
    assert unsupported_version_errors(_meta(server_version)) == []


def test_pre_8_baseline_rejected_with_pack_note() -> None:
    errors = unsupported_version_errors(_meta("5.7.40"))
    assert len(errors) == 1
    assert "not supported" in errors[0]
    assert "pack" in errors[0]  # 5.7 仅 pack 锁风险注记口径的提示必须带上


def test_unparsable_version_rejected() -> None:
    errors = unsupported_version_errors(_meta("not-a-version"))
    assert errors and "unparsable server version" in errors[0]
