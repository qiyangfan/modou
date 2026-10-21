"""lint 配置：modou.toml 的 [lint] 段（规则开关与数值阈值）。

命令行 --skip-rule 与配置 disable 取并集；未提供配置时默认全开并使用默认阈值。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from modou.lint.engine import Thresholds

DEFAULT_CONFIG_FILE = "modou.toml"


class LintConfigError(Exception):
    """配置文件不可读或形态非法（输入错误，退出码 2）。"""


@dataclass(frozen=True)
class LintConfig:
    disabled: frozenset[str] = frozenset()
    thresholds: Thresholds = field(default_factory=Thresholds)


def _parse_threshold(raw: dict, key: str, path: Path) -> int:
    """读取正整数阈值；布尔、非整浮点、负值和非数值都拒绝。"""
    value = raw.get(key, getattr(Thresholds, key))
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise LintConfigError(f"[lint].thresholds.{key} must be a positive integer in {path}")
    if isinstance(value, float) and not value.is_integer():
        raise LintConfigError(f"[lint].thresholds.{key} must be a positive integer in {path}")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise LintConfigError(f"[lint].thresholds.{key} must be a positive integer in {path}") from exc
    if number < 1:
        raise LintConfigError(f"[lint].thresholds.{key} must be a positive integer in {path}")
    return number


def load_lint_config(config_path: Path | None = None) -> LintConfig:
    """加载配置；显式路径必须存在，否则读取当前目录的 modou.toml。"""
    path = config_path if config_path is not None else Path(DEFAULT_CONFIG_FILE)
    if not path.exists():
        if config_path is not None:
            raise LintConfigError(f"config file not found: {path}")
        return LintConfig()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise LintConfigError(f"cannot read config {path}: {exc}") from exc
    lint = raw.get("lint", {})
    if not isinstance(lint, dict):
        raise LintConfigError(f"[lint] section must be a table in {path}")
    disabled_raw = lint.get("disable", [])
    if not isinstance(disabled_raw, list) or not all(isinstance(item, str) for item in disabled_raw):
        raise LintConfigError(f"[lint].disable must be an array of rule ids in {path}")
    thresholds_raw = lint.get("thresholds", {})
    if not isinstance(thresholds_raw, dict):
        raise LintConfigError(f"[lint].thresholds must be a table in {path}")
    thresholds = Thresholds(
        in_list=_parse_threshold(thresholds_raw, "in_list", path),
        offset=_parse_threshold(thresholds_raw, "offset", path),
        index_count=_parse_threshold(thresholds_raw, "index_count", path),
    )
    return LintConfig(disabled=frozenset(disabled_raw), thresholds=thresholds)
