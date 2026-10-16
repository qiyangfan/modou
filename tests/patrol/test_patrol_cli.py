"""patrol CLI 测试（离线路径）：drift 快照对比 / unused-indexes 离线 / slowlog。"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from modou.cli import app
from modou.snapshot.model import snapshot_to_json
from tests.optimize.conftest import make_orders_table, make_snapshot

runner = CliRunner()


class TestDriftCli:
    def test_drift_exit_1_with_findings(self, tmp_path) -> None:
        before = make_snapshot(with_sample=False)
        after = make_snapshot(with_sample=False)
        from modou.snapshot.model import IndexDef, IndexPart

        after.databases["shop"].tables["orders"].indexes = [
            *before.databases["shop"].tables["orders"].indexes,
            IndexDef("idx_extra", False, [IndexPart(1, "user_id", None, "A", None)]),
        ]
        b = tmp_path / "before.json"
        a = tmp_path / "after.json"
        b.write_text(snapshot_to_json(before), encoding="utf-8")
        a.write_text(snapshot_to_json(after), encoding="utf-8")
        result = runner.invoke(app, ["patrol", "drift", "--baseline", str(b), "--after", str(a)])
        assert result.exit_code == 1
        assert "新增" in result.output

    def test_drift_no_drift_exit_0(self, tmp_path) -> None:
        snap = make_snapshot(with_sample=False)
        b = tmp_path / "before.json"
        a = tmp_path / "after.json"
        b.write_text(snapshot_to_json(snap), encoding="utf-8")
        a.write_text(snapshot_to_json(snap), encoding="utf-8")
        result = runner.invoke(app, ["patrol", "drift", "--baseline", str(b), "--after", str(a)])
        assert result.exit_code == 0

    def test_drift_requires_after_or_dsn(self, tmp_path) -> None:
        b = tmp_path / "before.json"
        b.write_text(snapshot_to_json(make_snapshot(with_sample=False)), encoding="utf-8")
        result = runner.invoke(app, ["patrol", "drift", "--baseline", str(b)])
        assert result.exit_code == 2

    def test_drift_report_json(self, tmp_path) -> None:
        snap = make_snapshot(with_sample=False)
        b = tmp_path / "b.json"
        a = tmp_path / "a.json"
        b.write_text(snapshot_to_json(snap), encoding="utf-8")
        a.write_text(snapshot_to_json(snap), encoding="utf-8")
        out = tmp_path / "drift.json"
        result = runner.invoke(
            app, ["patrol", "drift", "--baseline", str(b), "--after", str(a), "--report-json", str(out)]
        )
        assert result.exit_code == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["report_kind"] == "patrol_drift"
        assert payload["exit_code"] == 0


class TestUnusedIndexesCli:
    def test_offline_redundancy_from_snapshot(self, tmp_path) -> None:
        table = make_orders_table(with_sample=False)
        from modou.snapshot.model import IndexDef, IndexPart

        table.indexes.append(IndexDef("idx_user", False, [IndexPart(1, "user_id", None, "A", None)]))
        table.indexes.append(
            IndexDef(
                "idx_user_amount",
                False,
                [IndexPart(1, "user_id", None, "A", None), IndexPart(2, "amount", None, "A", None)],
            )
        )
        snap = make_snapshot(with_sample=False, tables=[table])
        f = tmp_path / "snap.json"
        f.write_text(snapshot_to_json(snap), encoding="utf-8")
        result = runner.invoke(app, ["patrol", "unused-indexes", "--snapshot", str(f)])
        assert result.exit_code == 0
        assert "冗余" in result.output
        assert "DROP INDEX `idx_user`" in result.output

    def test_requires_dsn_or_snapshot(self) -> None:
        result = runner.invoke(app, ["patrol", "unused-indexes"])
        assert result.exit_code == 2

    def test_dsn_requires_database(self, tmp_path) -> None:
        result = runner.invoke(app, ["patrol", "unused-indexes", "--dsn", "mysql://u:p@127.0.0.1:3306"])
        assert result.exit_code == 2

    def test_report_json(self, tmp_path) -> None:
        table = make_orders_table(with_sample=False)
        snap = make_snapshot(with_sample=False, tables=[table])
        f = tmp_path / "snap.json"
        f.write_text(snapshot_to_json(snap), encoding="utf-8")
        out = tmp_path / "unused.json"
        result = runner.invoke(app, ["patrol", "unused-indexes", "--snapshot", str(f), "--report-json", str(out)])
        assert result.exit_code == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["report_kind"] == "patrol_unused_indexes"
        assert payload["exit_code"] == 0


class TestSlowlogCli:
    def test_aggregation(self, tmp_path) -> None:
        f = tmp_path / "slow.log"
        f.write_text(
            "# Query_time: 1.5 Lock_time: 0.0002 Rows_sent: 10 Rows_examined: 100000\n"
            "SET timestamp=1792730400;\n"
            "SELECT * FROM orders WHERE user_id = 42;\n"
            "# Query_time: 2.5 Lock_time: 0.0001 Rows_sent: 10 Rows_examined: 200000\n"
            "SET timestamp=1792730405;\n"
            "SELECT * FROM orders WHERE user_id = 77;\n",
            encoding="utf-8",
        )
        result = runner.invoke(app, ["patrol", "slowlog", str(f)])
        assert result.exit_code == 0
        assert "墨斗慢日志聚合报告" in result.output
        assert "次数 2" in result.output

    def test_missing_file_exit_2(self, tmp_path) -> None:
        result = runner.invoke(app, ["patrol", "slowlog", str(tmp_path / "nope.log")])
        assert result.exit_code == 2

    def test_report_json(self, tmp_path) -> None:
        f = tmp_path / "slow.log"
        f.write_text(
            "# Query_time: 1 Rows_sent: 1 Rows_examined: 10\nSET timestamp=1;\nSELECT 1 FROM t;\n",
            encoding="utf-8",
        )
        out = tmp_path / "slowlog.json"
        result = runner.invoke(app, ["patrol", "slowlog", str(f), "--report-json", str(out)])
        assert result.exit_code == 0
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["report_kind"] == "patrol_slowlog"
        assert payload["entries_parsed"] == 1


class TestPatrolSummarizeCli:
    """patrol summarize：跨信号 digest + AI 叙事（配置驱动、退出码取最严重档）。"""

    def _drift_json(self, tmp_path):
        f = tmp_path / "drift.json"
        f.write_text(
            json.dumps(
                {
                    "report_kind": "patrol_drift",
                    "report_version": 1,
                    "exit_code": 1,
                    "summary": {"added": 1, "removed": 0, "changed": 0, "databases_with_findings": 1},
                    "databases": {},
                }
            ),
            encoding="utf-8",
        )
        return f

    def test_requires_at_least_one_input(self, tmp_path) -> None:
        result = runner.invoke(app, ["patrol", "summarize"])
        assert result.exit_code == 2

    def test_kind_mismatch_exit_two(self, tmp_path) -> None:
        wrong = tmp_path / "w.json"
        wrong.write_text(json.dumps({"report_kind": "lint", "report_version": 1}), encoding="utf-8")
        result = runner.invoke(app, ["patrol", "summarize", "--drift", str(wrong)])
        assert result.exit_code == 2
        assert "report_kind" in result.output

    def test_digest_without_ai_has_no_opinions(self, tmp_path, monkeypatch) -> None:
        for key in ("MOUDO_AI_BASE_URL", "MOUDO_AI_API_KEY", "MOUDO_AI_MODEL"):
            monkeypatch.delenv(key, raising=False)

        def must_not_call(*args, **kwargs):
            raise AssertionError("AI narrative must not run without BYOK config")

        monkeypatch.setattr("modou.ai.lane_patrol.narrativize", must_not_call)
        drift = self._drift_json(tmp_path)
        out = tmp_path / "summary.json"
        result = runner.invoke(app, ["patrol", "summarize", "--drift", str(drift), "--report-json", str(out)])
        assert result.exit_code == 1  # 取最严重档：drift 有发现
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["report_kind"] == "patrol_summary"
        assert "ai_opinions" not in payload
        assert "AI 观点" not in result.output

    def test_ai_narrative_attached_exit_code_immunity(self, tmp_path, monkeypatch) -> None:
        from modou.report.opinions import AiOpinion

        monkeypatch.setenv("MOUDO_AI_BASE_URL", "https://api.example.com/v1")
        monkeypatch.setenv("MOUDO_AI_API_KEY", "k")
        monkeypatch.setenv("MOUDO_AI_MODEL", "glm-4.7")

        def fake_narrative(summary, *, config, **kwargs):
            assert config.model == "glm-4.7"
            return [AiOpinion(lane="patrol", subject="cross-signal", opinion="漂移与慢日志相互印证。", model="glm-4.7")]

        monkeypatch.setattr("modou.ai.lane_patrol.narrativize", fake_narrative)
        drift = self._drift_json(tmp_path)
        out = tmp_path / "summary.json"
        result = runner.invoke(app, ["patrol", "summarize", "--drift", str(drift), "--report-json", str(out)])
        assert result.exit_code == 1
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["ai_opinions"][0]["subject"] == "cross-signal"
        assert payload["exit_code"] == 1
        assert "AI 观点" in result.output and "未实证" in result.output
