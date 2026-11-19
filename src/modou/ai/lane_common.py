"""AI 观点条目的公共解析：只保留指向批内对象的非空文本。"""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from modou.report.opinions import AiOpinion


def parse_opinions(items: list[Any], lane: str, subjects: Collection[str], model: str) -> list[AiOpinion]:
    opinions: list[AiOpinion] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        subject = item.get("subject")
        text = item.get("opinion")
        if not isinstance(subject, str) or subject not in subjects:
            continue
        if not isinstance(text, str) or not text.strip():
            continue
        opinions.append(AiOpinion(lane=lane, subject=subject, opinion=text.strip(), model=model))
    return opinions
