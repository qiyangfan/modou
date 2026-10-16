"""verify 失败归因（内置通道，design §5）：三方 diff 事实 → AI 解释成因与修复建议。

- 零差异（exit 0 且无回放错误）零调用：没有需要归因的对象；
- 事实包 = 确定性结论（对象/类别/维度/期望实际值）+ 变更集语句（回放序号定位）
  + schema 切片（触达裁剪，slicer 单源，只取 baseline——变更集新建表的定义经
  语句全文在场，不依赖切片；漏执行场景下 after 快照同样缺该表，取了也补不到点）；
  仅元数据与 SQL 文本，绝无数据行；
- 输出逐条校验（subject 必须指向真实结论对象，幻觉条目丢弃）；调用失败降级为
  单条 report 级 degraded 观点；
- 只产出 report.opinions.AiOpinion，退出码免疫。
"""

from __future__ import annotations

from pathlib import Path

from modou.ai.client import (
    DEFAULT_TIMEOUT_SECONDS,
    AiCallError,
    AiConfig,
    Transport,
    chat_content,
    default_transport,
    extract_json_array,
)
from modou.ai.slicer import slice_schema
from modou.changeset.pack import pack_changeset
from modou.replay.splitter import split_statements
from modou.report.opinions import AiOpinion, degraded
from modou.snapshot.model import Snapshot

LANE = "verify"

# 事实包规模上限：结论对象数与单条期望/实际文本长度（约束载荷，不做语义截断承诺）
_MAX_CONCLUSIONS = 40
_MAX_DETAIL_CHARS = 500

_SYSTEM_PROMPT = (
    "You are a senior MySQL DBA explaining verification findings. Facts given: deterministic "
    "three-way diff conclusions (missing_execution / wrong_execution / historical_drift), the "
    "changeset statements (in replay order) and touched schema metadata. Explain per finding the "
    "likely cause (e.g. skipped statement, wrong column order, parallel change) and a concrete "
    "remedy. Respond with ONLY a JSON array; each item is "
    '{"subject":"<subject exactly as given>","opinion":"<short paragraph in Chinese>"}. '
    "No prose outside JSON."
)


def attribute_findings(
    report_json: dict,
    changeset_dir: Path,
    baseline: Snapshot,
    *,
    config: AiConfig,
    transport: Transport = default_transport,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    default_database: str | None = None,
    allow_legacy_names: bool = False,
) -> list[AiOpinion]:
    """对验收报告的差异结论做归因；零差异零调用，失败降级不阻塞报告。"""
    facts = _extract_facts(report_json)
    if facts is None:
        return []
    conclusion_subjects, conclusions, replay_error = facts
    try:
        packed = pack_changeset(Path(changeset_dir), allow_legacy_names=allow_legacy_names).packed_sql
        statements = [
            {"subject": f"#{index}", "sql": statement}
            for index, statement in enumerate(split_statements(packed), start=1)
        ]
        schema = slice_schema([entry["sql"] for entry in statements], baseline, default_database=default_database)
    except Exception as exc:  # 事实打包段任何失败（含切片异常）都按降级披露，不阻塞验收报告
        return [degraded(LANE, "report", config.model, f"cannot prepare attribution facts: {exc}")]
    user_payload = {
        "conclusions": conclusions,
        "replay_error": replay_error,
        "statements": statements,
        "schema": schema,
    }
    try:
        content = chat_content(
            config,
            system=_SYSTEM_PROMPT,
            user_payload=user_payload,
            transport=transport,
            timeout_seconds=timeout_seconds,
        )
    except AiCallError as exc:
        return [degraded(LANE, "report", config.model, str(exc))]
    items = extract_json_array(content)
    if items is None:
        # 回复不可解析同属调用失败（spec「调用失败降级」）：标注原因，不静默缺席
        return [degraded(LANE, "report", config.model, "unparseable reply (no JSON array)")]
    opinions: list[AiOpinion] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        subject = item.get("subject")
        text = item.get("opinion")
        if not isinstance(subject, str) or subject not in conclusion_subjects:
            continue  # 幻觉定位丢弃
        if not isinstance(text, str) or not text.strip():
            continue
        opinions.append(AiOpinion(lane=LANE, subject=subject, opinion=text.strip(), model=config.model))
    return opinions


def _extract_facts(report_json: dict) -> tuple[set[str], list[dict], dict | None] | None:
    """从报告 JSON 提取归因事实：无差异（零结论且无回放错误）返回 None（零调用）。"""
    conclusions: list[dict] = []
    subjects: set[str] = set()
    for db_name, db_conclusions in (report_json.get("databases") or {}).items():
        for conclusion in db_conclusions:
            subject = f"{db_name}.{conclusion.get('object_type')}:{conclusion.get('object_name')}"
            subjects.add(subject)
            conclusions.append(
                {
                    "subject": subject,
                    "kind": conclusion.get("kind"),
                    "dimensions": conclusion.get("dimensions"),
                    "details": [
                        {
                            "dimension": detail.get("dimension"),
                            "path": detail.get("path"),
                            "expected": _cap(str(v)) if (v := detail.get("expected")) is not None else None,
                            "actual": _cap(str(v)) if (v := detail.get("actual")) is not None else None,
                        }
                        for detail in (conclusion.get("details") or [])
                    ],
                }
            )
            if len(conclusions) >= _MAX_CONCLUSIONS:
                break
        if len(conclusions) >= _MAX_CONCLUSIONS:
            break
    replay_error = report_json.get("replay_error")
    if not conclusions and replay_error is None:
        return None
    if replay_error is not None:
        subjects.add("replay")
    return subjects, conclusions, replay_error


def _cap(text: str, limit: int = _MAX_DETAIL_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"
