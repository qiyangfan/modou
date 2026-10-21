"""_resolve_params 单测：DSN 解析、口令优先级与空口令保留（纯函数，离线可测）。"""

from __future__ import annotations

import pytest
import typer

from modou.params import resolve_params as _resolve_params


def test_dsn_explicit_empty_password_is_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    """`mysql://u:@h` 的空口令是显式配置，不能被 env 或交互提示覆盖。"""
    monkeypatch.delenv("MOUDO_MYSQL_PASSWORD", raising=False)
    params = _resolve_params("mysql://u:@h1:3307", None, None, None, None)
    assert params.password == ""
    assert (params.host, params.port, params.user) == ("h1", 3307, "u")


def test_percent_encoded_password_is_decoded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOUDO_MYSQL_PASSWORD", raising=False)
    params = _resolve_params("mysql://u:p%40ss@h", None, None, None, None)
    assert params.password == "p@ss"


def test_dsn_password_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """DSN 中的口令优先于环境变量。"""
    monkeypatch.setenv("MOUDO_MYSQL_PASSWORD", "envpass")
    params = _resolve_params("mysql://u:dsnpass@h", None, None, None, None)
    assert params.password == "dsnpass"


def test_env_falls_back_when_dsn_has_no_password(monkeypatch: pytest.MonkeyPatch) -> None:
    """DSN 无口令时使用 env 口令，不受优先级反转影响。"""
    monkeypatch.setenv("MOUDO_MYSQL_PASSWORD", "envpass")
    params = _resolve_params("mysql://u@h", None, None, None, None)
    assert params.password == "envpass"


def test_env_empty_string_counts_as_provided(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOUDO_MYSQL_PASSWORD", "")
    params = _resolve_params("mysql://u@h", None, None, None, None)
    assert params.password == ""


def test_flag_beats_env_and_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOUDO_MYSQL_PASSWORD", "envpass")
    params = _resolve_params("mysql://u:dsnpass@h", None, None, None, "flagpass")
    assert params.password == "flagpass"


def test_missing_password_prompts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOUDO_MYSQL_PASSWORD", raising=False)
    monkeypatch.setattr(typer, "prompt", lambda *args, **kwargs: "prompted")
    params = _resolve_params(None, "h", None, None, None)
    assert params.password == "prompted"
