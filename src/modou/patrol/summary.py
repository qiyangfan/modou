"""跨信号综合摘要（patrol summarize）：三份巡检报告的确定性 digest。

- 只做确定性聚合（计数、清单封顶），跨信号的语义关联留给 AI 叙事
  （ai/lane_patrol，配置驱动）——digest 本身零网络、零 AI 依赖；
- 输入必须是各自槽位对应的 report_kind（错位 = 输入错误），防张冠李戴；
- 退出码取已加载信号的最严重档（drift 0/1；其余建议性输出恒 0）。
"""

from __future__ import annotations

from datetime import UTC, datetime

REPORT_VERSION = 1

_KIND_BY_SIGNAL = {
    "drift": "patrol_drift",
    "unused": "patrol_unused_indexes",
    "slowlog": "patrol_slowlog",
}

_MAX_OBJECTS = 20
_MAX_TOP = 3


class SummaryInputError(Exception):
    """输入文件不可读、缺信号或 report_kind 错位（映射退出码 2）。"""


def summarize_reports(
    drift: dict | None,
    unused: dict | None,
    slowlog: dict | None,
    *,
    inputs: dict[str, str | None] | None = None,
) -> dict:
    """聚合三份巡检报告为一份综合摘要（report_kind=patrol_summary）。

    输入形状强校验（非 dict / report_kind 错位 / exit_code 非整数 / 消费段形状
    不符 → SummaryInputError，映射退出码 2）——畸形报告不得以裸异常或假「发现」
    档收场（退出码契约：1=存在发现，2=输入错误）。
    """
    loaded = {"drift": drift, "unused": unused, "slowlog": slowlog}
    if all(report is None for report in loaded.values()):
        raise SummaryInputError("at least one of --drift/--unused/--slowlog is required")
    for signal, report in loaded.items():
        if report is None:
            continue
        if not isinstance(report, dict):
            raise SummaryInputError(f"{signal} report must be a JSON object")
        if report.get("report_kind") != _KIND_BY_SIGNAL[signal]:
            raise SummaryInputError(
                f"{signal} slot expects report_kind={_KIND_BY_SIGNAL[signal]!r}, got {report.get('report_kind')!r}"
            )

    signals: dict = {}
    if drift is not None:
        summary = _section(drift, "summary", dict, "drift")
        databases = _section(drift, "databases", dict, "drift")
        signals["drift"] = {
            "exit_code": _exit_code(drift, "drift"),
            "added": summary.get("added", 0),
            "removed": summary.get("removed", 0),
            "changed": summary.get("changed", 0),
            "objects": [
                {
                    "database": db_name,
                    "object_type": conclusion.get("object_type"),
                    "object_name": conclusion.get("object_name"),
                    "category": conclusion.get("category"),
                }
                for db_name, conclusions in databases.items()
                if isinstance(conclusions, list)
                for conclusion in conclusions
                if isinstance(conclusion, dict)
            ][:_MAX_OBJECTS],
        }
    if unused is not None:
        usages = _section(unused, "usages", list, "unused")
        redundancies = _section(unused, "redundancies", list, "unused")
        usage_items = [u for u in usages if isinstance(u, dict)]
        signals["unused"] = {
            "exit_code": _exit_code(unused, "unused"),
            "uptime_seconds": unused.get("uptime_seconds"),
            "observe_days": unused.get("observe_days"),
            "confirmed_unused": sum(1 for u in usage_items if u.get("status") == "confirmed_unused"),
            "low_use": sum(1 for u in usage_items if u.get("status") == "low_use"),
            "insufficient_data": sum(1 for u in usage_items if u.get("status") == "insufficient_data"),
            "redundant": len(redundancies),
            "items": [
                {
                    "database": u.get("database"),
                    "table": u.get("table"),
                    "index": u.get("index_name"),
                    "status": u.get("status"),
                }
                for u in usage_items
            ][:_MAX_OBJECTS],
        }
    if slowlog is not None:
        top = _section(slowlog, "top", list, "slowlog")
        top_items = [a for a in top if isinstance(a, dict)]
        signals["slowlog"] = {
            "exit_code": _exit_code(slowlog, "slowlog"),
            "entries_parsed": slowlog.get("entries_parsed", 0),
            "fingerprints": len(top_items),
            "top": [
                {
                    "fingerprint": agg.get("fingerprint"),
                    "count": agg.get("count"),
                    "query_time_total": agg.get("query_time_total"),
                    "rows_examined_total": agg.get("rows_examined_total"),
                }
                for agg in top_items
            ][:_MAX_TOP],
        }

    exit_codes = [int(signal["exit_code"]) for signal in signals.values()]
    # 退出码归一保留档位：2=任一输入报告带环境错误档，1=存在发现，0=无发现
    summary_exit = 2 if any(code >= 2 for code in exit_codes) else (1 if any(code >= 1 for code in exit_codes) else 0)
    return {
        "report_kind": "patrol_summary",
        "report_version": REPORT_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "exit_code": summary_exit,
        "inputs": inputs if inputs is not None else {signal: None for signal in _KIND_BY_SIGNAL},
        "signals": signals,
    }


def _section(report: dict, key: str, expected: type, signal: str) -> dict | list:
    """取报告的消费段并校验形状（缺席按空处理，类型不符 = 输入错误）。"""
    value = report.get(key)
    if value is None:
        return expected()
    if not isinstance(value, expected):
        raise SummaryInputError(f"{signal} report field {key!r} must be {expected.__name__}")
    return value


def _exit_code(report: dict, signal: str) -> int:
    value = report.get("exit_code", 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise SummaryInputError(f"{signal} report exit_code must be an integer, got {value!r}")
    return int(value)


def summarize_render(report: dict) -> str:
    """人读文本：逐信号摘要行 + 退出码（观点区由 opinions 模块追加）。"""
    lines = ["墨斗综合巡检报告", "＝" * 40]
    signals = report.get("signals") or {}
    if "drift" in signals:
        s = signals["drift"]
        lines.append(f"漂移：新增 {s['added']} · 缺失 {s['removed']} · 定义变更 {s['changed']}")
    if "unused" in signals:
        s = signals["unused"]
        lines.append(
            f"未用索引：确认未用 {s['confirmed_unused']} · 疑似低用 {s['low_use']}"
            f" · 数据不足 {s['insufficient_data']} · 冗余 {s['redundant']}"
        )
    if "slowlog" in signals:
        s = signals["slowlog"]
        lines.append(f"慢日志：解析 {s['entries_parsed']} 条，聚合 {s['fingerprints']} 个指纹")
    lines.append("")
    lines.append(f"退出码：{report['exit_code']}（0=无发现，1=存在发现，2=环境或输入错误）")
    return "\n".join(lines)
