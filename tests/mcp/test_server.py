"""MCP 工具封装测试：pack/version 正路径、错误翻译（无堆栈泄漏）、stdio 无端口。

容器依赖路径（verify/optimize）在影子集成测试覆盖（test_demo_flow.py）。
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

import pytest

pytest.importorskip("fastmcp", reason="MCP surface tests need the fastmcp dependency")

from fastmcp import Client

from modou.server import build_mcp_server


def _server():
    return build_mcp_server()


def call(server, tool: str, arguments: dict | None = None):
    async def run():
        async with Client(server) as client:
            return await client.call_tool(tool, arguments or {})

    return asyncio.run(run())


def call_expect_error(server, tool: str, arguments: dict | None = None) -> str:
    async def run():
        async with Client(server) as client:
            try:
                await client.call_tool(tool, arguments or {})
            except Exception as exc:  # ToolError
                return str(exc)
        raise AssertionError("expected tool error")

    return asyncio.run(run())


class TestPackTool:
    def test_pack_returns_warnings_and_exit_code(self, tmp_path) -> None:
        changeset = tmp_path / "cs"
        changeset.mkdir()
        (changeset / "V01__create_t.sql").write_text("CREATE TABLE t (id int);\n", encoding="utf-8")
        (changeset / "manifest.txt").write_text("V01__create_t.sql\n", encoding="utf-8")
        result = call(_server(), "pack", {"changeset_dir": str(changeset)})
        data = result.data
        assert data["exit_code"] == 0
        assert "CREATE TABLE t" in data["packed_sql"]
        assert isinstance(data["warnings"], list)

    def test_pack_validation_error_is_tool_error_without_stacktrace(self, tmp_path) -> None:
        changeset = tmp_path / "cs"
        changeset.mkdir()
        # manifest 声明了不存在的文件 → 校验失败
        (changeset / "manifest.txt").write_text("V09__missing.sql\n", encoding="utf-8")
        message = call_expect_error(_server(), "pack", {"changeset_dir": str(changeset)})
        assert "changeset validation failed" in message
        assert "Traceback" not in message
        assert ".py" not in message  # 内部路径不泄漏

    def test_pack_writes_output_file(self, tmp_path) -> None:
        changeset = tmp_path / "cs"
        changeset.mkdir()
        (changeset / "V01__create_t.sql").write_text("CREATE TABLE t (id int);\n", encoding="utf-8")
        (changeset / "manifest.txt").write_text("V01__create_t.sql\n", encoding="utf-8")
        output = tmp_path / "packed.sql"
        result = call(_server(), "pack", {"changeset_dir": str(changeset), "output": str(output)})
        assert result.data["packed_written_to"] == str(output)
        assert "CREATE TABLE" in output.read_text(encoding="utf-8")
        assert result.data["packed_sql"] is None

    def test_pack_bad_param_is_tool_error(self, tmp_path) -> None:
        message = call_expect_error(_server(), "pack", {"changeset_dir": str(tmp_path / "nope")})
        assert "failed" in message.lower()


class TestVersionTool:
    def test_version_reports_kernel_version(self) -> None:
        from modou import __version__

        result = call(_server(), "version")
        assert result.data == {"exit_code": 0, "version": __version__}


class TestSnapshotCaptureTool:
    def test_missing_password_is_tool_error_not_hang(self, tmp_path, monkeypatch) -> None:
        """stdio 面禁止交互提示：口令缺失必须立即报工具错误（而非挂起等待输入）。"""
        monkeypatch.delenv("MOUDO_MYSQL_PASSWORD", raising=False)
        message = call_expect_error(
            _server(),
            "snapshot_capture",
            {"database": ["shop"], "output": str(tmp_path / "s.json"), "dsn": "mysql://u@127.0.0.1:3306"},
        )
        assert "password" in message.lower()

    def test_bad_dsn_scheme_is_tool_error(self, tmp_path) -> None:
        message = call_expect_error(
            _server(),
            "snapshot_capture",
            {
                "database": ["shop"],
                "output": str(tmp_path / "s.json"),
                "dsn": "postgres://u:p@h:3306",
                "password": "x",
            },
        )
        assert "scheme" in message.lower()


class TestStdioOnly:
    def test_server_process_opens_no_listening_socket(self) -> None:
        """构建并列举工具（等价于 server 已在进程内运行）：不得出现任何监听套接字。"""
        import asyncio
        import shutil

        if shutil.which("lsof") is None:
            pytest.skip("lsof not available")

        from fastmcp import Client

        server = _server()

        async def run():
            async with Client(server) as client:
                await client.list_tools()

        before = _listening_ports()
        asyncio.run(run())
        after = _listening_ports()
        assert after <= before, f"new listening sockets appeared: {after - before}"


def _listening_ports() -> set[str]:
    import os
    import subprocess

    result = subprocess.run(
        ["lsof", "-nP", "-i", "-a", "-p", str(os.getpid())],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    listeners: set[str] = set()
    for line in result.stdout.splitlines():
        if "LISTEN" in line:
            listeners.add(line.strip())
    return listeners


class TestReviewRegressions:
    def test_lint_unknown_skip_rule_is_tool_error(self, tmp_path) -> None:
        """与 CLI 同语义：拼错的规则 id 拒绝，静默并入会改变审核结论口径。"""
        target = tmp_path / "a.sql"
        target.write_text("SELECT * FROM t WHERE a LIKE '%x'\n", encoding="utf-8")
        message = call_expect_error(_server(), "lint", {"paths": [str(target)], "skip_rule": ["TOTALLY_UNKNOWN_RULE"]})
        assert "unknown rule" in message

    def test_unused_indexes_observe_days_zero_is_tool_error(self) -> None:
        message = call_expect_error(
            _server(),
            "patrol_unused_indexes",
            {"dsn": "mysql://root@127.0.0.1:1/x", "database": ["shop"], "observe_days": 0},
        )
        assert "observe_days" in message


class TestEvidenceAlignment:
    """证据原语与命令机读出口的一致性校验（spec ai-analyst「宿主委托面」）。"""

    def test_snapshot_capture_summary_is_kernel_summary(self, tmp_path, monkeypatch) -> None:
        """快照摘要单一事实源：MCP 工具出口 == 内核 snapshot_summary（CLI --report-json 同源）。"""
        from modou.snapshot.model import DatabaseInventory, Snapshot, SnapshotMeta
        from modou.snapshot.summary import snapshot_summary

        captured = Snapshot(
            format_version=2,
            tool_version="test",
            captured_at="2026-10-16T00:00:00+00:00",
            meta=SnapshotMeta("8.4.11", "MySQL", "utf8mb4", "utf8mb4_0900_ai_ci", 0, ""),
            databases={"shop": DatabaseInventory(name="shop", charset="utf8mb4", collation="")},
        )
        monkeypatch.setattr("modou.server.capture_to_file", lambda *args, **kwargs: captured)
        result = call(
            _server(),
            "snapshot_capture",
            {
                "database": ["shop"],
                "output": str(tmp_path / "s.json"),
                "dsn": "mysql://u:p@127.0.0.1:3306",
            },
        )
        assert result.data["exit_code"] == 0
        assert result.data["summary"] == snapshot_summary(captured)

    def test_lint_machine_exit_matches_cli_report(self, tmp_path) -> None:
        """lint 命中：MCP 工具的 report 与 CLI --report-json 同源同构。"""
        import json

        from typer.testing import CliRunner

        from modou.cli import app

        target = tmp_path / "a.sql"
        target.write_text("SELECT * FROM t WHERE a LIKE '%x%'\n", encoding="utf-8")
        report_file = tmp_path / "lint.json"
        cli_result = CliRunner().invoke(app, ["lint", str(target), "--report-json", str(report_file)])
        assert cli_result.exit_code == 1
        tool = call(_server(), "lint", {"paths": [str(target)]})
        assert tool.data["exit_code"] == 1
        assert tool.data["report"] == json.loads(report_file.read_text(encoding="utf-8"))

    def test_lint_ai_opinions_flow_through_tool(self, tmp_path, monkeypatch) -> None:
        """MCP lint 与 CLI 同车道：配置后观点进 report，退出码不受影响。"""
        from modou.report.opinions import AiOpinion

        monkeypatch.setenv("MOUDO_AI_BASE_URL", "https://api.example.com/v1")
        monkeypatch.setenv("MOUDO_AI_API_KEY", "k")
        monkeypatch.setenv("MOUDO_AI_MODEL", "glm-4.7")
        opinion = AiOpinion(lane="lint", subject="a.sql:1", opinion="顺序依赖风险。", model="glm-4.7")

        def fake_review(*args, **kwargs):
            return [opinion]

        monkeypatch.setattr("modou.ai.lane_lint.review_residual", fake_review)
        target = tmp_path / "a.sql"
        target.write_text("SELECT * FROM t WHERE a LIKE '%x'\n", encoding="utf-8")
        result = call(_server(), "lint", {"paths": [str(target)]})
        assert result.data["exit_code"] == 1
        assert result.data["report"]["ai_opinions"][0]["subject"] == "a.sql:1"

    def test_verify_ai_opinions_flow_through_tool(self, tmp_path, monkeypatch) -> None:
        """MCP verify 与 CLI 同车道：配置后归因观点进 report，退出码不受影响。"""
        from modou.report.opinions import AiOpinion

        monkeypatch.setenv("MOUDO_AI_BASE_URL", "https://api.example.com/v1")
        monkeypatch.setenv("MOUDO_AI_API_KEY", "k")
        monkeypatch.setenv("MOUDO_AI_MODEL", "glm-4.7")

        def fake_attribute(*args, **kwargs):
            return [AiOpinion(lane="verify", subject="report", opinion="归因解释。", model="glm-4.7")]

        monkeypatch.setattr("modou.ai.lane_verify.attribute_findings", fake_attribute)
        changeset = tmp_path / "cs"
        changeset.mkdir()
        (changeset / "V01__a.sql").write_text("SELECT 1;\n", encoding="utf-8")
        (changeset / "manifest.txt").write_text("V01__a.sql\n", encoding="utf-8")

        class FakeOutcome:
            exit_code = 1
            report_json: ClassVar[dict] = {"report_version": 1, "exit_code": 1, "databases": {"shop": []}}

        monkeypatch.setattr("modou.server.run_verify", lambda *args, **kwargs: FakeOutcome())
        from modou.snapshot.model import DatabaseInventory, Snapshot, SnapshotMeta, snapshot_to_json

        baseline = tmp_path / "b.json"
        baseline.write_text(
            snapshot_to_json(
                Snapshot(
                    format_version=2,
                    tool_version="t",
                    captured_at="c",
                    meta=SnapshotMeta("8.4.11", "MySQL", "utf8mb4", "utf8mb4_0900_ai_ci", 0, ""),
                    databases={"shop": DatabaseInventory(name="shop", charset="utf8mb4", collation="")},
                )
            ),
            encoding="utf-8",
        )
        result = call(
            _server(),
            "verify",
            {"changeset_dir": str(changeset), "baseline": str(baseline), "after": str(baseline)},
        )
        assert result.data["exit_code"] == 1
        assert result.data["report"]["ai_opinions"][0]["subject"] == "report"
