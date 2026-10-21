"""CLI 表面层用例：pack 退出码与产物、verify 输入校验（不含容器，影子逻辑由集成测试覆盖）。"""

import subprocess
import sys
from pathlib import Path
from typing import ClassVar

from typer.testing import CliRunner

from modou.cli import app
from modou.snapshot.model import Snapshot, SnapshotMeta, snapshot_to_json

runner = CliRunner()


def _valid_snapshot_json() -> str:
    return snapshot_to_json(
        Snapshot(
            format_version=1,
            tool_version="test",
            captured_at="2026-10-14T00:00:00+00:00",
            meta=SnapshotMeta(
                server_version="8.4.11",
                version_comment="test",
                character_set_server="utf8mb4",
                collation_server="utf8mb4_0900_ai_ci",
                lower_case_table_names=0,
                sql_mode="",
            ),
        )
    )


def make_changeset(tmp_path: Path, files: dict[str, str], manifest: list[str] | None = None) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    if manifest is not None:
        (tmp_path / "manifest.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")
    return tmp_path


def test_pack_writes_file_and_stderr_warnings(tmp_path: Path) -> None:
    changeset = make_changeset(
        tmp_path / "cs",
        {
            "V01__create.sql": "CREATE TABLE t (id INT);",
            "V02__drop.sql": "DROP TABLE old_t;",
        },
        ["V01__create.sql", "V02__drop.sql"],
    )
    output = tmp_path / "packed.sql"
    result = runner.invoke(app, ["pack", str(changeset), "--output", str(output)])
    assert result.exit_code == 0, result.output
    packed = output.read_text(encoding="utf-8")
    assert "CREATE TABLE t" in packed and "DROP TABLE old_t" in packed
    assert packed.index("V01__create.sql") < packed.index("DROP TABLE")
    # 破坏性预警可见
    assert "destructive" in result.output


def test_pack_rejects_missing_manifest_exit_one(tmp_path: Path) -> None:
    changeset = make_changeset(tmp_path / "cs", {"V01__a.sql": "SELECT 1;"}, manifest=None)
    result = runner.invoke(app, ["pack", str(changeset)])
    assert result.exit_code == 1
    assert "manifest missing" in result.output


def test_pack_rejects_inconsistent_manifest_exit_one(tmp_path: Path) -> None:
    changeset = make_changeset(tmp_path / "cs", {"V01__a.sql": "SELECT 1;"}, manifest=[])
    result = runner.invoke(app, ["pack", str(changeset)])
    assert result.exit_code == 1
    assert "not declared" in result.output


def test_pack_rejects_duplicate_seq_exit_one(tmp_path: Path) -> None:
    changeset = make_changeset(
        tmp_path / "cs",
        {"V01__a.sql": "SELECT 1;", "V001__b.sql": "SELECT 2;"},
        ["V01__a.sql", "V001__b.sql"],
    )
    result = runner.invoke(app, ["pack", str(changeset)])
    assert result.exit_code == 1
    assert "duplicate sequence" in result.output


def test_pack_report_json(tmp_path: Path) -> None:
    import json

    changeset = make_changeset(tmp_path / "cs", {"V01__a.sql": "DROP TABLE t;"}, ["V01__a.sql"])
    report = tmp_path / "warnings.json"
    result = runner.invoke(app, ["pack", str(changeset), "--report-json", str(report)])
    assert result.exit_code == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload[0]["kind"] == "destructive"


def test_verify_bad_snapshot_file_exit_two(tmp_path: Path) -> None:
    changeset = make_changeset(tmp_path / "cs", {"V01__a.sql": "SELECT 1;"}, ["V01__a.sql"])
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    result = runner.invoke(
        app,
        ["verify", str(changeset), "--baseline", str(bad), "--after", str(bad)],
    )
    assert result.exit_code == 2
    assert "cannot load snapshot" in result.output


def test_verify_changeset_validation_error_exit_two(tmp_path: Path) -> None:
    """变更集校验失败应走 VerifyInputError 并返回 2，不能被快照加载错误抢先。"""
    changeset = make_changeset(tmp_path / "cs", {"V01__a.sql": "SELECT 1;"})  # 无 manifest
    baseline = tmp_path / "b.json"
    baseline.write_text(_valid_snapshot_json(), encoding="utf-8")
    result = runner.invoke(
        app,
        ["verify", str(changeset), "--baseline", str(baseline), "--after", str(baseline)],
    )
    assert result.exit_code == 2
    assert "changeset validation failed" in result.output


def test_pack_invalid_target_major_exit_two(tmp_path: Path) -> None:
    changeset = make_changeset(tmp_path / "cs", {"V01__a.sql": "SELECT 1;"}, ["V01__a.sql"])
    result = runner.invoke(app, ["pack", str(changeset), "--target-major", "9.0"])
    assert result.exit_code == 2
    assert "unsupported target major" in result.output


def test_pack_stdout_is_pure_sql_when_redirected(tmp_path: Path) -> None:
    """stdout 只允许 SQL 产物，预警一律走 stderr。"""
    changeset = make_changeset(tmp_path / "cs", {"V01__drop.sql": "DROP TABLE old_t;"}, ["V01__drop.sql"])
    proc = subprocess.run(
        [sys.executable, "-m", "modou.cli", "pack", str(changeset)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "[destructive]" not in proc.stdout
    assert proc.stdout.strip().endswith(";")
    assert "[destructive]" in proc.stderr


def test_capture_connection_failure_exit_two(tmp_path: Path) -> None:
    """采集失败（连接拒绝）属环境错误，退出码 2；1 只用于「存在差异」。"""
    output = tmp_path / "s.json"
    result = runner.invoke(
        app,
        [
            "snapshot",
            "capture",
            "--host",
            "127.0.0.1",
            "--port",
            "1",
            "-d",
            "nope",
            "-o",
            str(output),
            "--password",
            "x",
        ],
    )
    assert result.exit_code == 2
    assert "snapshot capture failed" in result.output


def test_capture_report_json_is_kernel_summary(tmp_path: Path, monkeypatch) -> None:
    """CLI --report-json 与内核 snapshot_summary 输出逐字节一致。"""
    import json

    from modou.snapshot.model import DatabaseInventory
    from modou.snapshot.summary import snapshot_summary

    captured = Snapshot(
        format_version=2,
        tool_version="test",
        captured_at="2026-10-16T00:00:00+00:00",
        meta=SnapshotMeta("8.4.11", "MySQL", "utf8mb4", "utf8mb4_0900_ai_ci", 0, ""),
        databases={"shop": DatabaseInventory(name="shop", charset="utf8mb4", collation="")},
    )
    monkeypatch.setattr("modou.cli.capture_to_file", lambda *args, **kwargs: captured)
    output = tmp_path / "s.json"
    report = tmp_path / "summary.json"
    result = runner.invoke(
        app,
        ["snapshot", "capture", "-d", "shop", "-o", str(output), "--report-json", str(report), "--password", "x"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload == snapshot_summary(captured)


class TestVerifyAiAttribution:
    """verify 失败归因接线：配置后观点进报告，退出码不变。"""

    def test_unconfigured_no_ai_call_no_section(self, tmp_path, monkeypatch) -> None:
        for key in ("MOUDO_AI_BASE_URL", "MOUDO_AI_API_KEY", "MOUDO_AI_MODEL"):
            monkeypatch.delenv(key, raising=False)

        def must_not_call(*args, **kwargs):
            raise AssertionError("AI attribution must not run without BYOK config")

        monkeypatch.setattr("modou.ai.lane_verify.attribute_findings", must_not_call)
        changeset = make_changeset(tmp_path / "cs", {"V01__a.sql": "SELECT 1;"}, ["V01__a.sql"])
        baseline = tmp_path / "b.json"
        baseline.write_text(_valid_snapshot_json(), encoding="utf-8")

        class FakeOutcome:
            exit_code = 1
            report_json: ClassVar[dict] = {
                "report_version": 1,
                "exit_code": 1,
                "databases": {"shop": [{"object_name": "orders"}]},
            }

            def render(self):
                return "墨斗验收报告"

        # 桩掉容器回放，让 AI 分支可达；未配置时 tripwire 不得触发
        monkeypatch.setattr("modou.cli.run_verify", lambda *args, **kwargs: FakeOutcome())
        # AI 归因先于报告落盘；报告文件缺失即说明命令中途退出
        report = tmp_path / "verify-report.json"
        result = runner.invoke(
            app,
            [
                "verify",
                str(changeset),
                "--baseline",
                str(baseline),
                "--after",
                str(baseline),
                "--report-json",
                str(report),
            ],
        )
        assert result.exit_code == 1
        assert "AI 观点" not in result.output
        assert report.exists(), "tripwire fired: verify aborted before writing report (AI ran unconfigured)"
        import json

        assert "ai_opinions" not in json.loads(report.read_text(encoding="utf-8"))

    def test_configured_attaches_opinions_exit_code_immunity(self, tmp_path, monkeypatch) -> None:
        import json

        from modou.report.opinions import AiOpinion

        monkeypatch.setenv("MOUDO_AI_BASE_URL", "https://api.example.com/v1")
        monkeypatch.setenv("MOUDO_AI_API_KEY", "k")
        monkeypatch.setenv("MOUDO_AI_MODEL", "glm-4.7")
        captured: dict = {}

        def fake_attribute(report_json, changeset_dir, baseline, *, config, **kwargs):
            captured["exit_code"] = report_json["exit_code"]
            captured["model"] = config.model
            return [AiOpinion(lane="verify", subject="report", opinion="漏执行疑似运维侧跳过 V03。", model="glm-4.7")]

        monkeypatch.setattr("modou.ai.lane_verify.attribute_findings", fake_attribute)

        # 退出码 1 的场景由集成测试覆盖，这里用桩造确定性结论
        class FakeOutcome:
            exit_code = 1
            report_json: ClassVar[dict] = {
                "report_version": 1,
                "exit_code": 1,
                "databases": {"shop": [{"object_name": "orders"}]},
            }

            def render(self):
                return "墨斗验收报告"

        monkeypatch.setattr("modou.cli.run_verify", lambda *args, **kwargs: FakeOutcome())
        changeset = make_changeset(tmp_path / "cs", {"V01__a.sql": "SELECT 1;"}, ["V01__a.sql"])
        baseline = tmp_path / "b.json"
        baseline.write_text(_valid_snapshot_json(), encoding="utf-8")
        out = tmp_path / "report.json"
        result = runner.invoke(
            app,
            [
                "verify",
                str(changeset),
                "--baseline",
                str(baseline),
                "--after",
                str(baseline),
                "--report-json",
                str(out),
            ],
        )
        assert result.exit_code == 1  # 退出码仍由确定性结论决定
        assert captured["exit_code"] == 1 and captured["model"] == "glm-4.7"
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["ai_opinions"][0]["subject"] == "report"
        assert report["exit_code"] == 1
        assert "AI 观点" in result.output and "未实证" in result.output
