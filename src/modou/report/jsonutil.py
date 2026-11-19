"""报告机读 JSON 与单行文本压缩的公共实现。"""

from __future__ import annotations

import json
from typing import Any


def dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def one_line(text: str, limit: int = 160) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 3] + "..."
