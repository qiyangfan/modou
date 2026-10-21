"""生成 SQL 优化报告（report_kind=optimize）。

建议标记为「实测提升」或「未验证」；退出码只反映报告成败，不受 AI 观点影响。
"""

from __future__ import annotations

import json

REPORT_VERSION = 1
REPORT_KIND = "optimize"

EXIT_OK = 0
EXIT_ERROR = 2

STATUS_MEASURED = "measured"
STATUS_UNVERIFIED = "unverified"

STATUS_LABELS: dict[str, str] = {
    STATUS_MEASURED: "实测提升",
    STATUS_UNVERIFIED: "未验证",
}


def report_to_json(report: dict) -> dict:
    """返回深拷贝并附报告格式标识。"""
    import copy

    payload = copy.deepcopy(report)
    payload["report_version"] = REPORT_VERSION
    payload["report_kind"] = REPORT_KIND
    return payload


def render_text(report: dict) -> str:
    """生成中文优化报告，按库列出语句、发现、建议状态与副作用。"""
    lines: list[str] = ["墨斗优化报告", "＝" * 40]

    for error in report.get("env_errors", []):
        lines.append(f"环境/输入错误：{error}")
    for error in report.get("input_errors", []):
        lines.append(f"输入错误：{error}")

    advisor = report.get("advisor", {})
    if not advisor.get("configured", False):
        lines.append("")
        lines.append("AI 顾问未配置（MOUDO_AI_BASE_URL / MOUDO_AI_API_KEY / MOUDO_AI_MODEL），仅规则层产出候选。")

    evidence = report.get("evidence_env", {})
    if evidence:
        lines.append("")
        lines.append(f"── 实证环境（{evidence.get('note', '')}）──")
        for table_info in evidence.get("tables", []):
            estimated = table_info.get("estimated_rows")
            estimated_text = "未知" if estimated is None else str(estimated)
            sampled = table_info.get("sampled_rows")
            sampled_text = "未采样（无数据支撑代价对比）" if sampled is None else f"采样 {sampled} 行"
            lines.append(
                f"  {table_info['database']}.{table_info['table']}：{sampled_text}（全表估计 {estimated_text} 行）"
            )

    databases = report.get("databases", {})
    for db_name, grouped in databases.items():
        statements = grouped.get("statements", []) if isinstance(grouped, dict) else grouped
        lines.append("")
        lines.append(f"── 库 {db_name} ──")
        _render_statements(lines, statements)

    if not databases and not report.get("env_errors") and not report.get("input_errors"):
        lines.append("")
        lines.append("无可分析语句。")

    lines.append("")
    lines.append(f"退出码：{report.get('exit_code', EXIT_ERROR)}（0=报告产出，2=环境或输入错误）")
    return "\n".join(lines)


def _render_statements(lines: list[str], statements: list[dict]) -> None:
    for statement in statements:
        lines.append("")
        lines.append(f"── 语句 #{statement['index']} ──")
        baseline = statement.get("baseline") or {}
        cost = baseline.get("cost")
        cost_text = "不可得" if cost is None else f"{cost:.2f}"
        lines.append(f"  SQL：{_one_line(statement['sql'])}")
        lines.append(f"  基线代价：{cost_text}")
        for finding in statement.get("findings", []):
            lines.append(f"  [发现] {finding['message']}")
        suggestions = statement.get("suggestions", [])
        if not suggestions:
            lines.append("  （无建议）")
        for suggestion in suggestions:
            status = suggestion["status"]
            source_label = "规则" if suggestion["source"] == "rule" else "AI"
            if status == STATUS_MEASURED:
                lines.append(
                    f"  [实测提升 {suggestion['improvement_pct']:.1f}%]（{source_label}）"
                    f" {_one_line(suggestion['content'])}"
                )
                lines.append(f"      代价 {suggestion['cost_before']:.2f} → {suggestion['cost_after']:.2f}")
            else:
                reason = suggestion.get("reason") or "原因未说明"
                lines.append(f"  [未验证]（{source_label}）{_one_line(suggestion['content'])}")
                lines.append(f"      原因：{reason}")
            for note in suggestion.get("side_effects", []):
                lines.append(f"      [附注·{note['kind']}] {note['message']}")


def dumps_json(report: dict) -> str:
    return json.dumps(report_to_json(report), ensure_ascii=False, indent=2) + "\n"


def _one_line(text: str, limit: int = 160) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 3] + "..."
