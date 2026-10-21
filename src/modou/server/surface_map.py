"""维护 CLI 分析命令到 MCP 工具的映射；工具名与描述取自 CLI。"""

from __future__ import annotations

import inspect

from modou.cli import app as cli_app

# mcp 与 ui 是交互式/长驻命令，不映射为分析工具。
EXCLUDED_COMMANDS = {"mcp", "ui"}

# 证据原语复用现有工具；三方 diff 和 EXPLAIN 由 verify/optimize 报告承载。
EVIDENCE_PRIMITIVES = {
    "snapshot_summary": "snapshot_capture",
    "replay_verify": "verify",
    "threeway_diff": "verify",
    "explain": "optimize",
    "lint_hits": "lint",
}


def _command_name(command) -> str:
    """返回命令名；Typer 未显式命名时回落函数名。"""
    if command.name:
        return command.name
    return command.callback.__name__ if command.callback and command.callback.__name__ != "<lambda>" else ""


def _command_help(command) -> str:
    """获取命令帮助文案；优先使用显式 help，否则读取回调的 docstring。"""
    if command.help:
        return command.help
    return inspect.getdoc(command.callback) if command.callback is not None else ""


def registered_cli_names() -> set[str]:
    """CLI 全部注册名（顶层命令 + 组名 + 组内命令的「组_命令」形），供守卫测试使用。"""
    names: set[str] = set()
    for command in cli_app.registered_commands:
        resolved = _command_name(command)
        if resolved:
            names.add(resolved)
    for group in cli_app.registered_groups:
        if not group.name:
            continue
        names.add(group.name)
        sub_app = group.typer_instance
        if sub_app is None:
            continue
        for command in sub_app.registered_commands:
            resolved = _command_name(command)
            if resolved:
                names.add(f"{group.name}_{resolved}")
    return names


def cli_command_map() -> dict[str, str]:
    """枚举 CLI 注册的分析类子命令：{工具名: help 文案}。

    嵌套组以下划线连接（snapshot capture → snapshot_capture）；连字符也归一下划线。
    """
    mapping: dict[str, str] = {}
    for command in cli_app.registered_commands:
        name = _command_name(command)
        if not name or name in EXCLUDED_COMMANDS:
            continue
        mapping[name.replace("-", "_")] = _command_help(command)
    for group in cli_app.registered_groups:
        group_name = group.name
        if not group_name or group_name in EXCLUDED_COMMANDS:
            continue
        sub_app = group.typer_instance
        if sub_app is None:
            continue
        for command in sub_app.registered_commands:
            name = _command_name(command)
            if not name:
                continue
            mapping[f"{group_name}_{name}".replace("-", "_")] = _command_help(command)
    return mapping
