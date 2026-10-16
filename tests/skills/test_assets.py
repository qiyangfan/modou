"""skills 资产随包分发测试：纯文本模板可经 importlib.resources 读取（零代码零依赖）。"""

from __future__ import annotations

import importlib.resources

SKILL_PATH = "skills/database-change-review/SKILL.md"


def _skill_text() -> str:
    return (importlib.resources.files("modou") / SKILL_PATH).read_text(encoding="utf-8")


class TestSkillAsset:
    def test_shipped_inside_package(self) -> None:
        text = _skill_text()
        assert text.startswith("# Skill：")

    def test_workflow_covers_evidence_primitives(self) -> None:
        """工作流模板必须覆盖委托面证据原语（与 surface_map 清单同源的工具名）。"""
        text = _skill_text()
        for tool in ("pack", "snapshot_capture", "verify", "lint", "optimize", "patrol_summarize"):
            assert tool in text, f"skill template missing tool {tool}"

    def test_states_exit_code_and_unverified_labels(self) -> None:
        """结论分级与红线是模板的核心契约：退出码语义与未实证标注必须在场。"""
        text = _skill_text()
        assert "exit_code" in text
        assert "未实证" in text
        assert "MOUDO_AI_BASE_URL" in text  # BYOK 三元组的零配置承诺
