"""optimize CLI 错误路径测试（无需容器）：退出码契约 0=报告产出 / 2=环境或输入错误。"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from modou.cli import app
from modou.snapshot.model import snapshot_to_json
from tests.optimize.conftest import make_snapshot

runner = CliRunner()


def _write_snapshot(tmp_path, *, with_sample: bool, format_version: int = 2):
    path = tmp_path / "baseline.json"
    path.write_text(
        snapshot_to_json(make_snapshot(with_sample=with_sample, format_version=format_version)), encoding="utf-8"
    )
    return path


class TestOptimizeCliErrors:
    def test_missing_baseline_file(self, tmp_path) -> None:
        statements = tmp_path / "slow.sql"
        statements.write_text("SELECT * FROM orders WHERE user_id = 1\n", encoding="utf-8")
        result = runner.invoke(app, ["optimize", str(statements), "--baseline", str(tmp_path / "nope.json")])
        assert result.exit_code == 2

    def test_structure_only_snapshot_rejected_with_hint(self, tmp_path) -> None:
        statements = tmp_path / "slow.sql"
        statements.write_text("SELECT * FROM orders WHERE user_id = 1\n", encoding="utf-8")
        baseline = _write_snapshot(tmp_path, with_sample=False)
        result = runner.invoke(app, ["optimize", str(statements), "--baseline", str(baseline)])
        assert result.exit_code == 2
        assert "--sample-rows" in result.output

    def test_ddl_input_rejected_naming_statement(self, tmp_path) -> None:
        statements = tmp_path / "slow.sql"
        statements.write_text("CREATE TABLE t (id int)\n", encoding="utf-8")
        baseline = _write_snapshot(tmp_path, with_sample=True)
        result = runner.invoke(app, ["optimize", str(statements), "--baseline", str(baseline)])
        assert result.exit_code == 2
        assert "statement #1" in result.output

    def test_unreadable_statements_file(self, tmp_path) -> None:
        baseline = _write_snapshot(tmp_path, with_sample=True)
        result = runner.invoke(app, ["optimize", str(tmp_path / "missing.sql"), "--baseline", str(baseline)])
        assert result.exit_code == 2

    def test_shadow_unavailable_maps_to_exit_2(self, tmp_path, monkeypatch) -> None:
        """容器不可用是环境错误：退出码 2，报告 JSON 含 env_errors。"""
        from modou.replay.container import ContainerRuntimeError

        def boom(*args, **kwargs):
            raise ContainerRuntimeError("no container runtime found (tried: podman, docker)")

        monkeypatch.setattr("modou.optimize.pipeline.ShadowMySQL.start", staticmethod(boom))
        statements = tmp_path / "slow.sql"
        statements.write_text("SELECT * FROM orders WHERE user_id = 1\n", encoding="utf-8")
        baseline = _write_snapshot(tmp_path, with_sample=True)
        report_path = tmp_path / "report.json"
        result = runner.invoke(
            app,
            [
                "optimize",
                str(statements),
                "--baseline",
                str(baseline),
                "--default-database",
                "shop",
                "--report-json",
                str(report_path),
            ],
        )
        assert result.exit_code == 2
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["exit_code"] == 2
        assert report["env_errors"]


class TestSnapshotCaptureSamplingFlag:
    def test_sample_rows_flag_registered(self) -> None:
        """确认 --sample-rows 已注册，不依赖终端渲染文本。"""
        result = runner.invoke(app, ["snapshot", "capture", "--help"])
        assert result.exit_code == 0
        import typer.main

        capture = typer.main.get_command(app).commands["snapshot"].commands["capture"]
        option_names = {opt for param in capture.params for opt in param.opts}
        assert "--sample-rows" in option_names
