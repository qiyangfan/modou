"""检查 MCP 工具与 CLI 分析类子命令一一对应。"""

from __future__ import annotations

import pytest

pytest.importorskip("fastmcp", reason="MCP surface tests need the fastmcp dependency")

from modou.server import build_mcp_server
from modou.server.surface_map import (
    EVIDENCE_PRIMITIVES,
    EXCLUDED_COMMANDS,
    cli_command_map,
    registered_cli_names,
)


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
        """排除清单只能包含真实存在的非分析命令，避免失效名单。"""
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
        """每个 MCP 工具都必须提供非空描述。"""
        descriptions = _tool_descriptions()
        assert descriptions, "no tools registered"
        empty = [name for name, text in descriptions.items() if not text.strip()]
        assert not empty, f"tools with empty description: {empty}"


class TestEvidenceParity:
    """检查证据原语映射；三方 diff 和 EXPLAIN 由 verify/optimize 报告承载。"""

    def test_primitive_set_frozen(self) -> None:
        assert set(EVIDENCE_PRIMITIVES) == {
            "snapshot_summary",
            "replay_verify",
            "threeway_diff",
            "explain",
            "lint_hits",
        }

    def test_primitives_point_to_registered_tools(self) -> None:
        tools = _tool_names()
        for primitive, tool in EVIDENCE_PRIMITIVES.items():
            assert tool in tools, f"evidence primitive {primitive!r} points to unregistered tool {tool!r}"
