"""parity 守护：MCP 工具与 CLI 分析类子命令 1:1（缺一或多一即失败，ADR-0002）。"""

from __future__ import annotations

import pytest

pytest.importorskip("fastmcp", reason="MCP surface tests need the fastmcp dependency")

from modou.server import build_mcp_server
from modou.server.surface_map import EXCLUDED_COMMANDS, cli_command_map, registered_cli_names


def _tool_names() -> set[str]:
    import asyncio

    server = build_mcp_server()

    async def collect() -> set[str]:
        from fastmcp import Client

        async with Client(server) as client:
            tools = await client.list_tools()
            return {tool.name for tool in tools}

    return asyncio.run(collect())


def _tool_descriptions() -> dict[str, str]:
    import asyncio

    server = build_mcp_server()

    async def collect() -> dict[str, str]:
        from fastmcp import Client

        async with Client(server) as client:
            tools = await client.list_tools()
            return {tool.name: (tool.description or "") for tool in tools}

    return asyncio.run(collect())


class TestParity:
    def test_tool_set_matches_cli_analysis_commands(self) -> None:
        mapping = cli_command_map()
        assert mapping, "CLI must expose analysis commands"
        assert set(mapping) == _tool_names(), (
            f"MCP tools and CLI analysis commands diverged: cli={sorted(mapping)}, mcp={sorted(_tool_names())}"
        )

    def test_excluded_commands_present_in_cli(self) -> None:
        """排除清单只许收录真实存在的非分析类命令（防名单腐化）。"""
        missing = EXCLUDED_COMMANDS - registered_cli_names()
        assert not missing, f"excluded commands no longer exist in CLI: {missing}"

    def test_tool_names_follow_sep986_safe_subset(self) -> None:
        for name in _tool_names():
            assert 1 <= len(name) <= 64
            assert name.replace("_", "a").isalnum(), f"tool name {name!r} outside safe charset"

    def test_descriptions_synced_with_cli_help(self) -> None:
        mapping = cli_command_map()
        descriptions = _tool_descriptions()
        for name, help_text in mapping.items():
            assert descriptions.get(name) == help_text, f"description drift for tool {name}"


class TestDescriptionGuard:
    def test_tool_descriptions_non_empty(self) -> None:
        """描述是 agent 工具发现的唯一依据：空串会让同源守卫空转（评审回归）。"""
        descriptions = _tool_descriptions()
        assert descriptions, "no tools registered"
        empty = [name for name, text in descriptions.items() if not text.strip()]
        assert not empty, f"tools with empty description: {empty}"
