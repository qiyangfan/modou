"""把 lint 命中按固定模板写入模型上下文，避免转述失真；无命中返回空串。"""

from __future__ import annotations

from collections.abc import Sequence

from modou.lint.engine import Hit

_RULE_CONTEXT_TEMPLATE = """已知静态规则命中（供参考，评审时避免重复报告同类问题）：
{lines}"""


def render_rule_context(hits: Sequence[Hit]) -> str:
    if not hits:
        return ""
    lines = [f"- [{hit.rule_id}] {hit.file}:{hit.line} {hit.message}" for hit in hits]
    return _RULE_CONTEXT_TEMPLATE.format(lines="\n".join(lines))
