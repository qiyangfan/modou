"""验收报告模型：人读文本 + 机读 JSON 双出口（report_version=1，契约冻结，ADR-0008）。

确定性退出码：0=全部一致；1=存在差异结论；2=环境或输入错误。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from modou.changeset.pack import StatementWarning
from modou.diff.threeway import KIND_DRIFT, KIND_MISSING, KIND_WRONG, ObjectConclusion

REPORT_VERSION = 1

EXIT_OK = 0
EXIT_DIFF = 1
EXIT_ERROR = 2

KIND_LABELS: dict[str, str] = {
    KIND_MISSING: "漏执行",
    KIND_WRONG: "错执行",
    KIND_DRIFT: "历史漂移",
}

OBJECT_TYPE_LABELS: dict[str, str] = {
    "database": "库",
    "table": "表",
    "view": "视图",
    "procedure": "存储过程",
    "function": "函数",
    "trigger": "触发器",
    "event": "事件",
}


@dataclass
class VerifyReport:
    generated_at: str
    exit_code: int
    env_errors: list[str] = field(default_factory=list)
    replay_error: dict | None = None
    pack_warnings: list[StatementWarning] = field(default_factory=list)
    databases: dict[str, list[ObjectConclusion]] = field(default_factory=dict)

    def conclusion_count(self, kind: str) -> int:
        return sum(1 for conclusions in self.databases.values() for c in conclusions if c.kind == kind)


def report_to_json(report: VerifyReport) -> dict:
    return {
        "report_version": REPORT_VERSION,
        "generated_at": report.generated_at,
        "exit_code": report.exit_code,
        "summary": {
            "missing_execution": report.conclusion_count(KIND_MISSING),
            "wrong_execution": report.conclusion_count(KIND_WRONG),
            "historical_drift": report.conclusion_count(KIND_DRIFT),
            "databases_with_findings": len(report.databases),
        },
        "env_errors": list(report.env_errors),
        "replay_error": report.replay_error,
        "pack_warnings": [
            {
                "source_file": w.source_file,
                "statement_index": w.statement_index,
                "kind": w.kind,
                "level": w.level,
                "message": w.message,
            }
            for w in report.pack_warnings
        ],
        "databases": {
            db_name: [
                {
                    "object_type": c.object_type,
                    "object_name": c.object_name,
                    "kind": c.kind,
                    "dimensions": c.dimensions,
                    "details": [
                        {
                            "dimension": d.dimension,
                            "path": d.path,
                            "expected": d.expected,
                            "actual": d.actual,
                        }
                        for d in c.details
                    ],
                }
                for c in conclusions
            ]
            for db_name, conclusions in report.databases.items()
        },
    }


def render_text(report: VerifyReport) -> str:
    """人读文本（中文正文）：按库分组，逐对象列结论与差异维度。"""
    lines: list[str] = ["墨斗验收报告", "＝" * 40]

    for error in report.env_errors:
        lines.append(f"环境/输入错误：{error}")
    if report.replay_error is not None:
        err = report.replay_error
        lines.append(f"回放失败：语句 #{err['statement_index']}（error {err['error_code']}）：{err['error_message']}")
        lines.append(f"失败语句：{_one_line(err['sql'])}")

    if report.pack_warnings:
        lines.append("")
        lines.append("── 打包预警（不影响验收结论）──")
        for w in report.pack_warnings:
            lines.append(f"  [{w.kind}] {w.source_file} #{w.statement_index}：{w.message}")

    if report.databases:
        total_by_kind = {kind: report.conclusion_count(kind) for kind in KIND_LABELS}
        for db_name, conclusions in report.databases.items():
            lines.append("")
            if len(report.databases) > 1:
                # 多库时计数只在尾部「汇总」行出现一次，库头不带计数（避免跨库误读）
                lines.append(f"── 库 {db_name} ──")
            else:
                counts = " · ".join(f"{label} {total_by_kind[kind]}" for kind, label in KIND_LABELS.items())
                lines.append(f"── 库 {db_name}（{counts}）──")
            for c in conclusions:
                dims = "、".join(c.dimension_labels) if c.dimensions else "-"
                type_label = OBJECT_TYPE_LABELS.get(c.object_type, c.object_type)
                lines.append(f"  [{KIND_LABELS[c.kind]}] {type_label} `{c.object_name}`（{dims}）")
                for d in c.details:
                    expected = _one_line(d.expected)
                    actual = _one_line(d.actual)
                    lines.append(f"      {d.path}: 期望 {expected}")
                    lines.append(f"      {d.path}: 实际 {actual}")
        if len(report.databases) > 1:
            counts = " · ".join(f"{label} {total_by_kind[kind]}" for kind, label in KIND_LABELS.items())
            lines.append("")
            lines.append(f"── 汇总（{counts}）──")
    elif not report.env_errors and report.replay_error is None:
        lines.append("")
        lines.append("全部一致：期望态与实际态逐对象逐维度相等。")

    lines.append("")
    lines.append(f"退出码：{report.exit_code}（0=全部一致，1=存在差异，2=环境或输入错误）")
    return "\n".join(lines)


def _one_line(text: str, limit: int = 160) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 3] + "..."
