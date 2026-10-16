"""AI 观点区契约（v0.5，ADR-0009 结论两级分级）：各车道报告的唯一口径。

- 实证已验证：报告既有正文字段（确定性代码 + 影子库实测），唯一决定退出码；
- AI 观点：ai_opinions 单列区，附来源与「未实证」标注，永不影响退出码；
- 未配置 BYOK：车道不产出观点，报告不含 ai_opinions 键——attach 空清单是
  恒等函数（未配置与 v0.4 零差异的机械保证，契约测试守护）；
- 调用失败：降级条目（status=degraded）标注原因，报告照常产出，退出码不变。
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
    """单条 AI 观点：对象定位 + 文本 + 来源标注（模型名）+ 状态。"""

    lane: str
    subject: str
    opinion: str
    model: str
    status: str = STATUS_OK
    degraded_reason: str | None = None


def degraded(lane: str, subject: str, model: str, reason: str) -> AiOpinion:
    """降级条目工厂：调用失败也进观点区（标注原因），不静默缺席。"""
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
    """把观点并入报告 JSON：空清单原样返回（零差异），否则浅拷贝加单键。

    不改写既有字段、不读不写 exit_code（退出码免疫由「从不接触」结构性保证）。
    """
    if not opinions:
        return report
    merged = dict(report)
    merged[AI_OPINIONS_KEY] = opinions_to_json(opinions)
    return merged


def render_opinions_section(opinions: Sequence[AiOpinion]) -> str:
    """人读文本的观点区（追加在报告正文之后）：空清单返回空串（无该区）。"""
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
