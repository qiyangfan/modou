"""检查影子库版本和平台参数是否与快照兼容。

不匹配时报错（退出码 2），不静默降级；影子库与目标库行为不一致时期望态不可信。
"""

from __future__ import annotations

from modou.snapshot.model import SnapshotMeta

# 依赖 8.0.13+ 的 STATISTICS.expression 与 8.0.16+ 的 CHECK_CONSTRAINTS；更老版本入口处拒绝。
# 5.7 只用于 pack 的锁风险注记。
MINIMUM_SUPPORTED_MAJOR = 8


def version_series(server_version: str) -> str:
    """取版本序列：'8.4.6' -> '8.4'（MySQL 版本序列 = 主.次，8.0/8.4/5.7 为不同序列）。"""
    parts = server_version.split("-")[0].split(".")
    return ".".join(parts[:2])


def unsupported_version_errors(meta: SnapshotMeta) -> list[str]:
    """返回版本低于支持下限的错误；空清单表示支持。"""
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
