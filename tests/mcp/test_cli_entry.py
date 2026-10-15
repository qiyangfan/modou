"""`modou mcp` 入口守卫：fastmcp 未安装 → 退出码 2 + 安装指引（不裸穿 traceback）。"""

from __future__ import annotations

import sys

from typer.testing import CliRunner

from modou.cli import app

runner = CliRunner()


def test_mcp_entry_missing_dependency_exit_2(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "fastmcp", None)  # import 处抛 ImportError（模拟未安装）
    result = runner.invoke(app, ["mcp"])
    assert result.exit_code == 2
    assert "modou[mcp]" in result.output
    assert "Traceback" not in result.output
