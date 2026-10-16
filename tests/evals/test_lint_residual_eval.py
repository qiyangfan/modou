"""评测回归门禁（v0.5 design §6）：提示词/模板/切片/规则注入的任何变更必跑评测。

两层：
- 确定性半区（恒跑）：数据集聚合性 + 上下文工程回归（残留面不丢语句、反例确实
  规则零命中、提示词契约字符串在场）——任何一层坏掉，门禁即失败，零密钥可跑；
- BYOK 半区（MOUDO_AI_* 三元组齐备才跑，镜像影子门禁模式）：真实端点逐案评审、
  计精度、落盘 last-run.json、劣化即失败。首版精度实测于 2026-10-16
  （qwen-plus @ DashScope：复跑 1.0，数字见 evals/README.md），
  地板据此校准。
"""

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

# 精度下限：2026-10-16 qwen-plus 首测校准（5 案各 0.2，容忍单案回归，两案劣化即阻塞）
ACCURACY_FLOOR = 0.8


def _units(case: dict) -> list[StatementUnit]:
    return [
        StatementUnit(file=f"{case['id']}.sql", line=index, sql=statement)
        for index, statement in enumerate(case["statements"], start=1)
    ]


class TestDatasetSanity:
    """确定性半区：数据集与上下文工程回归（零密钥门禁）。"""

    def test_positive_cases_are_fully_residual(self) -> None:
        """正例语句必须全部进残留面：残留提取丢语句 = AI 漏审，门禁失败。"""
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
        """提示词是评测资产：结构化输出契约与中文观点约束的字符串必须在场（三车道同律）。"""
        for prompt in (lane_lint._SYSTEM_PROMPT, lane_verify._SYSTEM_PROMPT, lane_patrol._SYSTEM_PROMPT):
            assert "JSON array" in prompt
            assert "Chinese" in prompt


class TestByokEvaluation:
    """BYOK 半区：真实端点精度门（三元组齐备才跑；未配置 skip，不假绿）。"""

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
            # 只有 status=ok 的观点算作命中；degraded 是评审通道故障，
            # 按失败计（README「评审整体降级阻塞合入」），不得伪装成精度数字。
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
