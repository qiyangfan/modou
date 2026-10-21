"""快照采集编排：采集并写入 JSON 文件。"""

from __future__ import annotations

from pathlib import Path

from modou.db import MysqlParams
from modou.snapshot.introspect import capture_snapshot
from modou.snapshot.model import Snapshot, snapshot_to_json


def write_snapshot(snapshot: Snapshot, output_path: Path) -> None:
    output_path.write_text(snapshot_to_json(snapshot), encoding="utf-8")


def capture_to_file(
    params: MysqlParams,
    database_names: list[str],
    output_path: Path,
    *,
    sample_rows: int | None = None,
) -> Snapshot:
    """采集指定库并写入 JSON 文件；sample_rows 给定时附带确定性样本。"""
    snapshot = capture_snapshot(params, database_names, sample_rows=sample_rows)
    write_snapshot(snapshot, output_path)
    return snapshot
