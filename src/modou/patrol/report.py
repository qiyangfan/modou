"""巡检报告渲染：人读文本 + 机读 JSON 双出口（三种巡检各一个 report_kind）。"""

from __future__ import annotations

import json
from dataclasses import asdict

from modou.patrol.drift import CATEGORY_LABELS, DriftReport
from modou.patrol.slowlog import SlowlogReport
from modou.patrol.unused_indexes import STATUS_LABELS, UnusedIndexesReport

REPORT_VERSION = 1


def drift_to_json(report: DriftReport) -> dict:
    return {
        "report_kind": "patrol_drift",
        "report_version": REPORT_VERSION,
        "exit_code": report.exit_code,
        "summary": {
            "added": report.count("added"),
            "removed": report.count("removed"),
            "changed": report.count("changed"),
            "databases_with_findings": len(report.conclusions),
        },
        "databases": {
            db_name: [
                {
                    "object_type": c.object_type,
                    "object_name": c.object_name,
                    "category": c.category,
                    "dimensions": c.dimensions,
                    "details": [asdict(d) for d in c.details],
                }
                for c in conclusions
            ]
            for db_name, conclusions in report.conclusions.items()
        },
    }


def drift_render(report: DriftReport) -> str:
    lines = ["墨斗漂移巡检报告", "＝" * 40]
    if not report.conclusions:
        lines.append("无漂移：两份快照结构等价。")
    for db_name, conclusions in report.conclusions.items():
        lines.append("")
        lines.append(f"── 库 {db_name} ──")
        for c in conclusions:
            lines.append(
                f"  [{CATEGORY_LABELS[c.category]}] {c.object_type} `{c.object_name}`（{'、'.join(c.dimensions)}）"
            )
            for d in c.details:
                lines.append(f"      {d.path}: 基线 {_one_line(d.expected)}")
                lines.append(f"      {d.path}: 当前 {_one_line(d.actual)}")
    lines.append("")
    lines.append(
        f"汇总：新增 {report.count('added')} · 缺失 {report.count('removed')} · 定义变更 {report.count('changed')}"
    )
    lines.append(f"退出码：{report.exit_code}（0=无漂移，1=存在漂移，2=环境或输入错误）")
    return "\n".join(lines)


def unused_to_json(report: UnusedIndexesReport) -> dict:
    return {
        "report_kind": "patrol_unused_indexes",
        "report_version": REPORT_VERSION,
        "exit_code": 0,
        "uptime_seconds": report.uptime_seconds,
        "observe_days": report.observe_days,
        "usages": [asdict(u) for u in report.usages],
        "redundancies": [asdict(r) for r in report.redundancies],
    }


def unused_render(report: UnusedIndexesReport) -> str:
    lines = ["墨斗索引巡检报告", "＝" * 40]
    if report.uptime_seconds is not None:
        days = report.uptime_seconds / 86400
        lines.append(f"服务器 uptime：{report.uptime_seconds}s（约 {days:.1f} 天）；观察窗 {report.observe_days} 天")
        lines.append("注意：I/O 统计会被服务器重启 / TRUNCATE 汇总表 / 索引 DDL 重置，结论请结合运行周期。")
    groups = [
        ("确认未用（附删除语句，执行归人）", [u for u in report.usages if u.status == "confirmed_unused"]),
        ("疑似低用", [u for u in report.usages if u.status == "low_use"]),
        ("数据不足", [u for u in report.usages if u.status == "insufficient_data"]),
        ("排除项", [u for u in report.usages if u.status.startswith("excluded_")]),
    ]
    for title, items in groups:
        if not items:
            continue
        lines.append("")
        lines.append(f"── {title}（{len(items)}）──")
        for u in items:
            meta = f"，读计数 {u.count_star}" if u.count_star else ""
            share = f"，占同表 I/O {u.table_share_pct}%" if u.table_share_pct is not None else ""
            daily = f"，日均 {u.daily_average}" if u.daily_average is not None else ""
            columns_text = ", ".join(u.columns)
            detail = f"{u.database}.{u.table}.{u.index_name} ({columns_text})"
            lines.append(f"  [{STATUS_LABELS[u.status]}] {detail}{meta}{share}{daily}")
            if u.note:
                lines.append(f"      {u.note}")
            if u.drop_statement:
                lines.append(f"      建议：{u.drop_statement}")
    if report.redundancies:
        lines.append("")
        lines.append(f"── 冗余索引（{len(report.redundancies)}）──")
        for r in report.redundancies:
            fk_note = "（被外键依赖，删除前需先处理外键）" if r.fk_protected else ""
            lines.append(
                f"  [冗余·{r.case}] {r.database}.{r.table}.{r.redundant_index} 被 {r.dominant_index} 覆盖{fk_note}"
            )
            lines.append(f"      建议：{r.drop_statement}")
    lines.append("")
    lines.append("退出码：0（建议性输出不构成验收结论；2=环境或输入错误）")
    return "\n".join(lines)


def slowlog_to_json(report: SlowlogReport) -> dict:
    return {
        "report_kind": "patrol_slowlog",
        "report_version": REPORT_VERSION,
        "exit_code": 0,
        "source_file": report.source_file,
        "entries_parsed": report.entries_parsed,
        "skipped_lines": report.skipped_lines,
        "top": [asdict(a) for a in report.top],
    }


def slowlog_render(report: SlowlogReport) -> str:
    lines = ["墨斗慢日志聚合报告", "＝" * 40]
    skipped_note = f"；跳过 {report.skipped_lines} 条（数值损坏）" if report.skipped_lines else ""
    lines.append(f"来源：{report.source_file}；解析条目 {report.entries_parsed}{skipped_note}")
    if not report.top:
        lines.append("无可聚合条目。")
    for position, agg in enumerate(report.top, start=1):
        lines.append("")
        lines.append(
            f"{position}. 次数 {agg.count} · 累计 {agg.query_time_total:.3f}s · 最大 {agg.query_time_max:.3f}s"
            f" · 扫描 {agg.rows_examined_total} 行"
        )
        lines.append(f"   指纹：{_one_line(agg.fingerprint, 120)}")
        lines.append(f"   样本：{_one_line(agg.sample)}")
    lines.append("")
    lines.append("退出码：0（建议性输出不构成验收结论；2=环境或输入错误）")
    return "\n".join(lines)


def dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _one_line(text: str, limit: int = 160) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 3] + "..."
