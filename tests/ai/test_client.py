"""BYOK 客户端异常边界测试：传输层任何异常都转成 AiCallError。"""

from __future__ import annotations

import http.client

import pytest

from modou.ai.client import AiCallError, AiConfig, complete


def _config() -> AiConfig:
    return AiConfig(base_url="https://api.example.com/v1", api_key="k", model="glm-4.7")


def _transport_raise(error: Exception):
    def transport(url: str, api_key: str, payload: dict, timeout: float) -> dict:
        raise error

    return transport


def test_http_exception_family_is_call_failure() -> None:
    """代理或网关断连异常也应转换为 AiCallError。"""
    with pytest.raises(AiCallError):
        complete(_config(), {}, transport=_transport_raise(http.client.BadStatusLine("''")))
    with pytest.raises(AiCallError):
        complete(_config(), {}, transport=_transport_raise(http.client.IncompleteRead(b"partial", 10)))


def test_empty_content_is_call_failure() -> None:
    """content 为 null 时按调用失败处理，不把字符串 "None" 交给解析层。"""

    def transport(url: str, api_key: str, payload: dict, timeout: float) -> dict:
        return {"choices": [{"message": {"content": None}}]}

    with pytest.raises(AiCallError, match="empty content"):
        complete(_config(), {}, transport=transport)


def test_transient_failure_is_retried() -> None:
    """一次通道故障（连接重置/半途截断）重试后成功。"""
    calls = []

    def flaky_transport(url: str, api_key: str, payload: dict, timeout: float) -> dict:
        calls.append(url)
        if len(calls) == 1:
            raise http.client.IncompleteRead(b"partial", 10)
        return {"choices": [{"message": {"content": "[]"}}]}

    assert complete(_config(), {}, transport=flaky_transport) == "[]"
    assert len(calls) == 2


def test_persistent_failure_raises_after_all_attempts() -> None:
    """持续失败时耗尽尝试次数后抛 AiCallError。"""
    calls = []

    def dead_transport(url: str, api_key: str, payload: dict, timeout: float) -> dict:
        calls.append(url)
        raise ConnectionResetError("reset")

    with pytest.raises(AiCallError):
        complete(_config(), {}, transport=dead_transport)
    assert len(calls) == 2


def test_ai_call_error_identity_preserved_after_retries() -> None:
    """重试后抛出的仍是同一个 AiCallError 实例，不二次包装。"""
    error = AiCallError("invalid AI endpoint response: boom")

    def transport(url: str, api_key: str, payload: dict, timeout: float) -> dict:
        raise error

    with pytest.raises(AiCallError) as exc_info:
        complete(_config(), {}, transport=transport)
    assert exc_info.value is error
