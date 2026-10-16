"""表面映射：CLI 子命令 ↔ MCP 工具的单一事实源（parity 测试据此守护）。

- 工具名 = CLI 子命令名（嵌套组以下划线连接），snake_case、纯字母数字下划线、
  ≤64 字符（SEP-986 最稳子集，部分客户端拒绝 `.`）；
- 描述与 CLI help 同文（agent 工具发现的唯一依据，两表面不得语义漂移）；
- 排除清单只收录「非分析类表面」：交互式或长驻能力（MCP 服务自身、报告 UI）——
  新增分析类子命令必须映射为工具，缺一或多一即 parity 失败。
"""

from __future__ import annotations

import inspect

from modou.cli import app as cli_app

# 非分析类表面：不映射为工具（结构性排除，与「新增车道必须映射」互补）。
# mcp = MCP 服务自身；ui = 长驻报告界面（均为交互式/长驻表面，ADR-0002）。
EXCLUDED_COMMANDS = {"mcp", "ui"}

# 委托面证据原语（ADR-0009 design §3）：原语 → 承载工具。三方 diff 与 EXPLAIN
# 由 verify/optimize 的机读出口（同一报告字段）承载，不另设工具——证据工具是
# 既有子命令机读出口的暴露，不新增 MCP 独有逻辑（1:1 契约的延伸）。
EVIDENCE_PRIMITIVES = {
    "snapshot_summary": "snapshot_capture",
    "replay_verify": "verify",
    "threeway_diff": "verify",
    "explain": "optimize",
    "lint_hits": "lint",
}


def _command_name(command) -> str:
    """typer 未显式命名时 CommandInfo.name 为 None，回落函数名（装饰器即函数名）。"""
    if command.name:
        return command.name
    return command.callback.__name__ if command.callback and command.callback.__name__ != "<lambda>" else ""


def _command_help(command) -> str:
    """命令帮助文案：typer 注册期 CommandInfo.help 为 None（docstring 要到 click
    构建期才回填），此处按 typer 自身的回退顺序取 inspect.getdoc，保证映射描述
    与 `--help` 同源（描述是 agent 工具发现的唯一依据，空串会让守卫空转）。"""
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

    嵌套 typer 组以下划线连接（snapshot capture → snapshot_capture）；连字符归一为
    下划线（patrol unused-indexes → patrol_unused_indexes，SEP-986 工具名最稳子集）。
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
