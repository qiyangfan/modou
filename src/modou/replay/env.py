"""检查影子库版本和平台参数是否与快照兼容。

不匹配时报错（退出码 2），不静默降级；影子库与目标库行为不一致时期望态不可信。
"""

from __future__ import annotations

from modou.snapshot.compat import version_series
from modou.snapshot.model import SnapshotMeta


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
