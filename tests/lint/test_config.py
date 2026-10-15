"""lint 配置加载测试：modou.toml 开关与阈值、显式缺失语义。"""

from __future__ import annotations

import pytest

from modou.lint.config import LintConfigError, load_lint_config
from modou.lint.engine import Thresholds


class TestLoadLintConfig:
    def test_no_config_anywhere_returns_defaults(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        config = load_lint_config()
        assert config.disabled == frozenset()
        assert config.thresholds == Thresholds()

    def test_explicit_missing_config_raises(self, tmp_path) -> None:
        with pytest.raises(LintConfigError, match="not found"):
            load_lint_config(tmp_path / "nope.toml")

    def test_disable_and_thresholds(self, tmp_path) -> None:
        f = tmp_path / "modou.toml"
        f.write_text(
            '[lint]\ndisable = ["ARG.006", "COL.005"]\n\n'
            "[lint.thresholds]\nin_list = 5\noffset = 100\nindex_count = 3\n",
            encoding="utf-8",
        )
        config = load_lint_config(f)
        assert config.disabled == frozenset({"ARG.006", "COL.005"})
        assert config.thresholds == Thresholds(in_list=5, offset=100, index_count=3)

    def test_partial_thresholds_fallback_to_defaults(self, tmp_path) -> None:
        f = tmp_path / "modou.toml"
        f.write_text("[lint.thresholds]\noffset = 50\n", encoding="utf-8")
        config = load_lint_config(f)
        assert config.thresholds.offset == 50
        assert config.thresholds.in_list == Thresholds.in_list

    def test_malformed_toml_raises(self, tmp_path) -> None:
        f = tmp_path / "broken.toml"
        f.write_text("[lint\ndisable = ", encoding="utf-8")
        with pytest.raises(LintConfigError):
            load_lint_config(f)

    def test_wrong_shape_raises(self, tmp_path) -> None:
        f = tmp_path / "modou.toml"
        f.write_text('[lint]\ndisable = "ARG.006"\n', encoding="utf-8")
        with pytest.raises(LintConfigError, match="array"):
            load_lint_config(f)

    def test_cwd_default_discovered(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "modou.toml").write_text('[lint]\ndisable = ["DIS.001"]\n', encoding="utf-8")
        assert load_lint_config().disabled == frozenset({"DIS.001"})


class TestThresholdValidation:
    def test_non_numeric_threshold_is_config_error(self, tmp_path) -> None:
        config = tmp_path / "modou.toml"
        config.write_text('[lint.thresholds]\nin_list = "abc"\n', encoding="utf-8")
        with pytest.raises(LintConfigError, match="in_list"):
            load_lint_config(config)

    def test_negative_threshold_rejected(self, tmp_path) -> None:
        config = tmp_path / "modou.toml"
        config.write_text("[lint.thresholds]\noffset = -5\n", encoding="utf-8")
        with pytest.raises(LintConfigError, match="offset"):
            load_lint_config(config)

    def test_fractional_float_rejected(self, tmp_path) -> None:
        config = tmp_path / "modou.toml"
        config.write_text("[lint.thresholds]\nindex_count = 3.7\n", encoding="utf-8")
        with pytest.raises(LintConfigError, match="index_count"):
            load_lint_config(config)

    def test_boolean_rejected(self, tmp_path) -> None:
        config = tmp_path / "modou.toml"
        config.write_text("[lint.thresholds]\nin_list = true\n", encoding="utf-8")
        with pytest.raises(LintConfigError, match="in_list"):
            load_lint_config(config)

    def test_valid_integer_accepted(self, tmp_path) -> None:
        config = tmp_path / "modou.toml"
        config.write_text("[lint.thresholds]\nin_list = 50\n", encoding="utf-8")
        assert load_lint_config(config).thresholds.in_list == 50
