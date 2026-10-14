"""影子库环境兼容性检查：版本与大版本、平台参数必须与快照一致（ADR-0005）。

不匹配明确报错（环境错误，退出码 2），绝不静默降级——影子库与目标库行为不一致时，
回放推导的期望态不可信。
"""

from __future__ import annotations

from modou.snapshot.model import SnapshotMeta

# 采集/内省依赖 8.0+ 专有元数据（STATISTICS.expression 于 8.0.13+、
# CHECK_CONSTRAINTS 表于 8.0.16+）：更老版本在查询期报晦涩错误，
# 入口处显式拒绝。5.7 仅 pack 锁风险注记口径（SUPPORTED_TARGET_MAJORS）。
MINIMUM_SUPPORTED_MAJOR = 8


def version_series(server_version: str) -> str:
    """取版本序列：'8.4.6' -> '8.4'（MySQL 版本序列 = 主.次，8.0/8.4/5.7 为不同序列）。"""
    parts = server_version.split("-")[0].split(".")
    return ".".join(parts[:2])


def unsupported_version_errors(meta: SnapshotMeta) -> list[str]:
    """返回「版本低于采集支持地板」的错误清单；空清单 = 支持。"""
    series = version_series(meta.server_version)
    try:
        major = int(series.split(".")[0])
    except ValueError:
        return [f"unparsable server version: {meta.server_version!r}"]
    if major < MINIMUM_SUPPORTED_MAJOR:
        return [
            f"MySQL {meta.server_version} is not supported for snapshot capture/verify "
            f"(minimum series: {MINIMUM_SUPPORTED_MAJOR}.0); "
            "5.7 is only supported for pack lock-risk notes (--target-major)"
        ]
    return []


def compatibility_errors(baseline_meta: SnapshotMeta, shadow_meta: SnapshotMeta) -> list[str]:
    """返回环境不兼容清单；空清单 = 可用。"""
    errors: list[str] = []
    baseline_series = version_series(baseline_meta.server_version)
    shadow_series = version_series(shadow_meta.server_version)
    if baseline_series != shadow_series:
        errors.append(
            f"version series mismatch: baseline server {baseline_meta.server_version} ({baseline_series}) "
            f"vs shadow {shadow_meta.server_version} ({shadow_series}); use a shadow image of the same series"
        )
    if baseline_meta.lower_case_table_names != shadow_meta.lower_case_table_names:
        errors.append(
            f"lower_case_table_names mismatch: baseline {baseline_meta.lower_case_table_names} "
            f"vs shadow {shadow_meta.lower_case_table_names}; object name resolution would differ"
        )
    return errors
