"""MCP 工具封装测试：pack/version 正路径、错误翻译（无堆栈泄漏）、stdio 无端口。

容器依赖路径（verify/optimize）在影子集成测试覆盖（test_demo_flow.py）。
"""

from __future__ import annotations

import asyncio

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
