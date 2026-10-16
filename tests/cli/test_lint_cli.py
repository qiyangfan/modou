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

    def test_parse_failure_recorded_exit_1(self, tmp_path) -> None:
        """解析失败逐语句记录为 PARSE.001 命中，退出码 1、整轮不中断（spec 2026-10-15 修订）。"""
        f = _write(tmp_path, "bad.sql", "SELECT 'unclosed\n")
        result = runner.invoke(app, ["lint", str(f)])
        assert result.exit_code == 1
        assert "PARSE.001" in result.output
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
        # 工具命中 PARSE.001 属合法跳过对象：仅含不可解析语句的输入跳过后恢复 0
        f2 = _write(tmp_path, "cond.sql", "SELECT 'unclosed\n")
        result3 = runner.invoke(app, ["lint", str(f2), "--skip-rule", "PARSE.001"])
        assert result3.exit_code == 0

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


class TestLintAiReview:
    """lint 残留语义评审的 CLI 接线：配置驱动、观点进报告、退出码免疫。"""

    def _spy_installed(self, monkeypatch, opinions):
        calls: list[dict] = []

        def fake_review(units, hits, config, **kwargs):
            calls.append({"subjects": [u.subject for u in units], "model": config.model})
            return opinions

        monkeypatch.setattr("modou.ai.lane_lint.review_residual", fake_review)
        return calls

    def test_unconfigured_makes_no_ai_call_and_report_unchanged(self, tmp_path, monkeypatch) -> None:
        """未配置 BYOK：不调 AI、报告无 ai_opinions、行为与 v0.4 一致（零网络回归）。"""
        monkeypatch.delenv("MOUDO_AI_BASE_URL", raising=False)
        monkeypatch.delenv("MOUDO_AI_API_KEY", raising=False)
        monkeypatch.delenv("MOUDO_AI_MODEL", raising=False)

        def must_not_call(*args, **kwargs):
            raise AssertionError("AI review must not be called without BYOK config")

        monkeypatch.setattr("modou.ai.lane_lint.review_residual", must_not_call)
        f = _write(tmp_path, "x.sql", "SELECT * FROM t WHERE a = 1\n")
        out = tmp_path / "lint.json"
        result = runner.invoke(app, ["lint", str(f), "--report-json", str(out)])
        assert result.exit_code == 1
        report = json.loads(out.read_text(encoding="utf-8"))
        assert "ai_opinions" not in report
        assert "AI 观点" not in result.output

    def test_configured_attaches_opinions_without_exit_code_change(self, tmp_path, monkeypatch) -> None:
        from modou.report.opinions import AiOpinion

        monkeypatch.setenv("MOUDO_AI_BASE_URL", "https://api.example.com/v1")
        monkeypatch.setenv("MOUDO_AI_API_KEY", "k")
        monkeypatch.setenv("MOUDO_AI_MODEL", "glm-4.7")
        opinion = AiOpinion(lane="lint", subject="x.sql:1", opinion="残留语句存在跨语句依赖风险。", model="glm-4.7")
        calls = self._spy_installed(monkeypatch, [opinion])
        f = _write(tmp_path, "x.sql", "SELECT * FROM t WHERE a = 1\n")
        out = tmp_path / "lint.json"
        result = runner.invoke(app, ["lint", str(f), "--report-json", str(out)])
        assert result.exit_code == 1  # 退出码仍由命中决定（COL.001 → 1）
        assert calls and calls[0]["model"] == "glm-4.7"
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["ai_opinions"][0]["subject"] == "x.sql:1"
        assert report["ai_opinions"][0]["source"] == "ai"
        assert report["exit_code"] == 1
        assert "AI 观点" in result.output and "未实证" in result.output
