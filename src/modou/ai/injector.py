"""规则注入器：lint 命中清单模板化注入（design §4）。

模板注入而非自然语言转述——OCR 的规则匹配经验：把机器事实（规则 id、位置、
消息）原样交给模型，转述层只会引入失真。空清单返回空串（无规则上下文区）。
"""

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
