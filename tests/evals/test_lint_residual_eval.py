"""AI 残留审核评测：始终检查确定性上下文；配置 BYOK 时评测真实端点精度。"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from modou.ai import lane_lint, lane_patrol, lane_verify
from modou.ai.bundler import StatementUnit
from modou.ai.client import AiConfig, config_from_env
from modou.ai.lane_lint import review_residual
from modou.lint import RULES
from modou.lint.engine import Thresholds, lint_sql_text, residual_statements

EVAL_DIR = Path(__file__).resolve().parents[2] / "evals" / "lint_residual"
CASES = json.loads((EVAL_DIR / "cases.json").read_text(encoding="utf-8"))["cases"]

ACCURACY_FLOOR = 0.8


def _units(case: dict) -> list[StatementUnit]:
    return [
        StatementUnit(file=f"{case['id']}.sql", line=index, sql=statement)
        for index, statement in enumerate(case["statements"], start=1)
    ]


class TestDatasetSanity:
    """检查数据集和上下文工程；无需 BYOK 配置。"""

    def test_positive_cases_are_fully_residual(self) -> None:
        """正例语句必须全部进入残留面，否则视为 AI 漏审。"""
        for case in CASES:
            if case["expect"] != "positive":
                continue
            text = ";\n".join(case["statements"]) + ";\n"
            hits = lint_sql_text(text, f"{case['id']}.sql", RULES, thresholds=Thresholds())
            assert not hits, f"{case['id']}: 正例被静态规则命中（不再是盲区），请改写数据集: {hits}"
            residual = residual_statements(text, RULES)
            assert len(residual) == len(case["statements"]), f"{case['id']}: 残留面丢语句"

    def test_negative_cases_are_rule_clean(self) -> None:
        for case in CASES:
            if case["expect"] != "negative":
                continue
            text = ";\n".join(case["statements"]) + ";\n"
            hits = lint_sql_text(text, f"{case['id']}.sql", RULES, thresholds=Thresholds())
            assert not hits, f"{case['id']}: 反例被规则命中（不是无害样本）: {hits}"

    def test_lane_prompts_carry_output_contract(self) -> None:
        """提示词是评测资产：结构化输出与中文观点约束必须在场。"""
        for prompt in (lane_lint._SYSTEM_PROMPT, lane_verify._SYSTEM_PROMPT, lane_patrol._SYSTEM_PROMPT):
            assert "JSON array" in prompt
            assert "Chinese" in prompt


class TestByokEvaluation:
    """真实端点精度门：三元组齐备才跑，未配置时 skip。"""

    @pytest.fixture()
    def byok_config(self) -> AiConfig:
        config = config_from_env(dict(__import__("os").environ))
        if config is None:
            pytest.skip("lint residual eval gated: set MOUDO_AI_BASE_URL/API_KEY/MODEL to run")
        return config

    @pytest.mark.needs_byok_env
    def test_residual_review_precision(self, byok_config: AiConfig) -> None:
        results = []
        correct = 0
        for case in CASES:
            opinions = review_residual(_units(case), [], byok_config)
            # 只有 status=ok 的观点计入结果；degraded 按失败处理。
            flagged = any(item.status == "ok" for item in opinions)
            degraded_hit = any(item.status != "ok" for item in opinions)
            expected = case["expect"] == "positive"
            ok = flagged == expected and not degraded_hit
            correct += ok
            results.append(
                {
                    "id": case["id"],
                    "expect": case["expect"],
                    "flagged": flagged,
                    "degraded": degraded_hit,
                    "degraded_reason": next((o.degraded_reason for o in opinions if o.status != "ok"), None),
                    "ok": ok,
                }
            )
        accuracy = correct / len(CASES)
        payload = {
            "eval": "lint_residual",
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "model": byok_config.model,
            "accuracy": round(accuracy, 4),
            "cases": results,
        }
        (EVAL_DIR / "last-run.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        assert accuracy >= ACCURACY_FLOOR, (
            f"lint residual eval degraded: accuracy={accuracy:.2f} < floor={ACCURACY_FLOOR}; "
            "see evals/lint_residual/last-run.json"
        )
