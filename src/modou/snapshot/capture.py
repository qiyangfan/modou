"""快照采集编排：采集 → 写文件。CLI 只做参数解析与展示，逻辑全部在内核库。"""

from __future__ import annotations

from pathlib import Path

from modou.db import MysqlParams
from modou.snapshot.introspect import capture_snapshot
from modou.snapshot.model import Snapshot, snapshot_to_json


def write_snapshot(snapshot: Snapshot, output_path: Path) -> None:
    output_path.write_text(snapshot_to_json(snapshot), encoding="utf-8")


def capture_to_file(params: MysqlParams, database_names: list[str], output_path: Path) -> Snapshot:
    """采集指定库清单并写入 JSON 文件，返回快照供调用方摘要展示。"""
    snapshot = capture_snapshot(params, database_names)
    write_snapshot(snapshot, output_path)
    return snapshot
