"""modou ui CLI 错误路径：报告缺失/未知类型/非回环绑定 → 退出码 2。"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from modou.cli import app

runner = CliRunner()


def _verify_file(tmp_path: Path) -> Path:
    f = tmp_path / "verify.json"
    f.write_text(
        json.dumps(
            {
                "report_version": 1,
                "exit_code": 0,
                "summary": {"missing_execution": 0, "wrong_execution": 0, "historical_drift": 0},
                "databases": {},
            }
        ),
        encoding="utf-8",
    )
    return f


class TestUiCli:
    def test_missing_report_exit_2(self, tmp_path) -> None:
        result = runner.invoke(app, ["ui", "--report", str(tmp_path / "nope.json"), "--no-open"])
        assert result.exit_code == 2
        assert "cannot read" in result.output

    def test_unknown_kind_exit_2(self, tmp_path) -> None:
        f = tmp_path / "alien.json"
        f.write_text(json.dumps({"report_kind": "alien", "report_version": 1}), encoding="utf-8")
        result = runner.invoke(app, ["ui", "--report", str(f), "--no-open"])
        assert result.exit_code == 2
        assert "supported reports" in result.output

    def test_non_loopback_bind_exit_2(self, tmp_path) -> None:
        result = runner.invoke(app, ["ui", "--report", str(_verify_file(tmp_path)), "--bind", "0.0.0.0", "--no-open"])
        assert result.exit_code == 2
        assert "loopback" in result.output
