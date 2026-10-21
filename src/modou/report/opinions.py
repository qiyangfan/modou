"""统一管理报告中的 AI 观点；观点独立于确定性结论和退出码。

未配置 BYOK 时报告不含 ``ai_opinions``；调用失败时添加带原因的降级条目。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

AI_OPINIONS_KEY = "ai_opinions"
SOURCE_AI = "ai"
STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"


@dataclass
class AiOpinion:
    """单条 AI 观点，包含定位、文本、模型名与状态。"""

    lane: str
    subject: str
    opinion: str
    model: str
    status: str = STATUS_OK
    degraded_reason: str | None = None


def degraded(lane: str, subject: str, model: str, reason: str) -> AiOpinion:
    """生成降级条目，让调用失败在观点区可见并注明原因。"""
    return AiOpinion(
        lane=lane, subject=subject, opinion="", model=model, status=STATUS_DEGRADED, degraded_reason=reason
    )


def opinions_to_json(opinions: Sequence[AiOpinion]) -> list[dict]:
    return [
        {
            "lane": o.lane,
            "subject": o.subject,
            "opinion": o.opinion,
            "source": SOURCE_AI,
            "model": o.model,
            "status": o.status,
            "degraded_reason": o.degraded_reason,
        }
        for o in opinions
    ]


def attach_ai_opinions(report: dict, opinions: Sequence[AiOpinion]) -> dict:
    """把观点并入报告 JSON；空清单原样返回，否则浅拷贝并添加 ai_opinions，不改动 exit_code。"""
    if not opinions:
        return report
    merged = dict(report)
    merged[AI_OPINIONS_KEY] = opinions_to_json(opinions)
    return merged


def render_opinions_section(opinions: Sequence[AiOpinion]) -> str:
    """生成人读观点区；空清单返回空串。"""
    if not opinions:
        return ""
    lines = ["", "── AI 观点（模型输出·未经实证·不影响退出码）──"]
    for o in opinions:
        if o.status == STATUS_DEGRADED:
            lines.append(f"  [{o.lane}] {o.subject}：AI 分析降级（{o.degraded_reason}）")
            continue
        lines.append(f"  [{o.lane}] {o.subject}（来源 ai:{o.model}·未实证）")
        for text_line in o.opinion.splitlines() or [""]:
            lines.append(f"      {text_line}")
    return "\n".join(lines)
