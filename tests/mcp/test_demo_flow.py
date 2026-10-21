"""MCP 演示流程：在一个会话中运行 pack、verify 和 optimize。"""

from __future__ import annotations

import json
from pathlib import Path

import pymysql
import pytest

pytest.importorskip("fastmcp", reason="MCP surface tests need the fastmcp dependency")

from fastmcp import Client

from tests.conftest import unique_db

CHANGESET = Path(__file__).resolve().parents[2] / "examples" / "changeset-demo"


def _read_statement(path: Path) -> str:
    """读变更文件并去掉尾部分隔符（直接 execute 单语句，与回放语义一致）。"""
    sql = path.read_text(encoding="utf-8").strip()
    return sql[:-1] if sql.endswith(";") else sql


def _build_demo_fixture(mysql_conn: pymysql.connections.Connection, shadow, tmp_path: Path) -> dict:
    """在影子容器中构造 before/after 快照和慢 SQL 文件，返回流程输入路径。"""
    db = unique_db("demo")
    from modou.snapshot.capture import capture_to_file

    with mysql_conn.cursor() as cursor:
        cursor.execute(f"CREATE DATABASE `{db}`")
    mysql_conn.commit()

    before_path = tmp_path / "before.json"
    capture_to_file(shadow.connect_params(), [db], before_path)

    # 「运维」执行 V01/V02、漏执行 V03/V04
    with mysql_conn.cursor() as cursor:
        mysql_conn.select_db(db)
        cursor.execute(_read_statement(CHANGESET / "V01__create_orders.sql"))
        cursor.execute(_read_statement(CHANGESET / "V02__alter_orders_add_remark.sql"))
        cursor.executemany(
            "INSERT INTO orders (user_id, amount, status) VALUES (%s, %s, %s)",
            [(i % 50, i * 1.5, i % 3) for i in range(1, 2001)],
        )
    mysql_conn.commit()

    after_path = tmp_path / "after.json"
    # after 快照带采样数据（500 行）：verify 消费结构部分，optimize 消费采样部分
    capture_to_file(shadow.connect_params(), [db], after_path, sample_rows=500)

    # verify 会把基线灌回影子库；先删源库，避免同名对象冲突（1050）
    with mysql_conn.cursor() as cursor:
        cursor.execute(f"DROP DATABASE `{db}`")
    mysql_conn.commit()

    slow_sql = tmp_path / "slow.sql"
    slow_sql.write_text("SELECT * FROM orders WHERE user_id = 42 AND amount > 10\n", encoding="utf-8")
    return {
        "database": db,
        "before": str(before_path),
        "after": str(after_path),
        "slow_sql": str(slow_sql),
    }


def test_agent_demo_chain_in_single_session(mysql_server, mysql_conn, tmp_path) -> None:
    from modou.server import build_mcp_server

    fixture = _build_demo_fixture(mysql_conn, mysql_server, tmp_path)
    server = build_mcp_server()

    async def chain():
        summary: list[str] = []
        async with Client(server) as client:
            # ① agent 打包变更集并读取破坏性预警
            pack = await client.call_tool("pack", {"changeset_dir": str(CHANGESET)})
            assert pack.data["exit_code"] == 0
            summary.append(f"pack ok, {len(pack.data['warnings'])} warning(s)")

            # ② agent 验收：影子回放 + 三方 diff，读退出码与结论
            verify = await client.call_tool(
                "verify",
                {
                    "changeset_dir": str(CHANGESET),
                    "baseline": fixture["before"],
                    "after": fixture["after"],
                    "default_database": fixture["database"],
                },
            )
            assert verify.data["exit_code"] == 1  # 漏执行场景：存在差异结论
            report = verify.data["report"]
            missing = report["summary"]["missing_execution"]
            assert missing >= 1, "漏执行的索引/存储过程必须被抓到"
            summary.append(f"verify exit=1, missing_execution={missing}")

            # ③ agent 优化慢 SQL：实测提升或未验证，读建议状态（基线 = 带采样的 after 快照）
            optimize = await client.call_tool(
                "optimize",
                {
                    "statements_file": fixture["slow_sql"],
                    "baseline": fixture["after"],
                    "default_database": fixture["database"],
                },
            )
            assert optimize.data["exit_code"] == 0
            grouped = optimize.data["report"]["databases"][fixture["database"]]["statements"]
            suggestions = [s for stmt in grouped for s in stmt["suggestions"]]
            assert suggestions, "rule candidates expected"
            assert all(s["status"] in ("measured", "unverified") for s in suggestions)
            summary.append(f"optimize suggestions={len(suggestions)}")
        return summary

    summary = asyncio_run(chain())
    # 汇总答句所需的三段结论齐备（pack 预警 / verify 差异 / optimize 建议）
    assert len(summary) == 3
    (tmp_path / "demo-summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)
