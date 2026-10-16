"""BYOK 客户端 fail-safe 边界测试：传输层任何异常都归入 AiCallError（车道据此降级）。"""

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
    """http.client.HTTPException 族（BadStatusLine/IncompleteRead）直接继承 Exception
    而非 OSError：代理/网关半途断连必须归入 AiCallError，不得穿透炸掉车道。"""
    with pytest.raises(AiCallError):
        complete(_config(), {}, transport=_transport_raise(http.client.BadStatusLine("''")))
    with pytest.raises(AiCallError):
        complete(_config(), {}, transport=_transport_raise(http.client.IncompleteRead(b"partial", 10)))


def test_ai_call_error_passes_through_unwrapped() -> None:
    """客户端内部（如响应 JSON 不可解析）抛出的 AiCallError 原样透传，不二次包装。"""
    error = AiCallError("invalid AI endpoint response: boom")
    with pytest.raises(AiCallError) as exc_info:
        complete(_config(), {}, transport=_transport_raise(error))
    assert exc_info.value is error


def test_empty_content_is_call_failure() -> None:
    """端点 200 但 content 为 null：归因为调用失败，而非把字符串 "None" 送进解析层。"""

    def transport(url: str, api_key: str, payload: dict, timeout: float) -> dict:
        return {"choices": [{"message": {"content": None}}]}

    with pytest.raises(AiCallError, match="empty content"):
        complete(_config(), {}, transport=transport)
