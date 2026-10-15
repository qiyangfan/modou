"""lint CLI 测试：退出码 0/1/2 契约、跳过规则、JSON 出口。"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from modou.cli import app

runner = CliRunner()


def _write(tmp_path, name: str, sql: str):
    f = tmp_path / name
    f.write_text(sql, encoding="utf-8")
    return f


class TestLintCli:
    def test_hits_exit_1(self, tmp_path) -> None:
        f = _write(tmp_path, "bad.sql", "SELECT * FROM orders\n")
        result = runner.invoke(app, ["lint", str(f)])
        assert result.exit_code == 1
        assert "COL.001" in result.output
        assert "墨斗审核报告" in result.output

    def test_clean_exit_0(self, tmp_path) -> None:
        f = _write(tmp_path, "good.sql", "SELECT id FROM orders WHERE id = 1\n")
        result = runner.invoke(app, ["lint", str(f)])
        assert result.exit_code == 0

    def test_parse_failure_exit_2(self, tmp_path) -> None:
        f = _write(tmp_path, "bad.sql", "SELECT 'unclosed\n")
        result = runner.invoke(app, ["lint", str(f)])
        assert result.exit_code == 2
        assert "bad.sql" in result.output

    def test_missing_path_exit_2(self, tmp_path) -> None:
        result = runner.invoke(app, ["lint", str(tmp_path / "nope.sql")])
        assert result.exit_code == 2

    def test_directory_input(self, tmp_path) -> None:
        sub = tmp_path / "cs"
        sub.mkdir()
        _write(sub, "V01__x.sql", "UPDATE t SET a = 1\n")
        _write(sub, "manifest.txt", "V01__x.sql\n")
        result = runner.invoke(app, ["lint", str(sub)])
        assert result.exit_code == 1
        assert "CLA.015" in result.output

    def test_skip_rule_overrides(self, tmp_path) -> None:
        f = _write(tmp_path, "x.sql", "SELECT * FROM t WHERE a = 1\n")
        result = runner.invoke(app, ["lint", str(f), "--skip-rule", "COL.001"])
        assert result.exit_code == 0
        # 未知规则 id = 输入错误（退出码 2）
        result2 = runner.invoke(app, ["lint", str(f), "--skip-rule", "NOPE.999"])
        assert result2.exit_code == 2

    def test_config_file_disable(self, tmp_path) -> None:
        f = _write(tmp_path, "x.sql", "SELECT * FROM t WHERE a = 1\n")
        cfg = _write(tmp_path, "modou.toml", '[lint]\ndisable = ["COL.001"]\n')
        result = runner.invoke(app, ["lint", str(f), "--config", str(cfg)])
        assert result.exit_code == 0

    def test_report_json(self, tmp_path) -> None:
        f = _write(tmp_path, "x.sql", "SELECT * FROM t WHERE a = 1\n")
        out = tmp_path / "lint.json"
        result = runner.invoke(app, ["lint", str(f), "--report-json", str(out)])
        assert result.exit_code == 1
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["report_kind"] == "lint"
        assert report["exit_code"] == 1
        assert any(h["rule_id"] == "COL.001" for h in report["hits"])
