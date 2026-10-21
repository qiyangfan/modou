"""调用 OpenAI 兼容的 BYOK 端点；传输层可注入，测试不触发真实网络。"""

from __future__ import annotations

import json
import re
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass

ENV_BASE_URL = "MOUDO_AI_BASE_URL"
ENV_API_KEY = "MOUDO_AI_API_KEY"
ENV_MODEL = "MOUDO_AI_MODEL"

DEFAULT_TIMEOUT_SECONDS = 30.0

Transport = Callable[[str, str, dict, float], dict]

_JSON_ARRAY_PATTERN = re.compile(r"\[.*\]", re.DOTALL)


def extract_json_array(content: str) -> list | None:
    """提取回复中的 JSON 数组；找不到或不是数组时返回 None。"""
    match = _JSON_ARRAY_PATTERN.search(content)
    if match is None:
        return None
    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return items if isinstance(items, list) else None


class AiCallError(Exception):
    """BYOK 调用失败（网络/超时/响应不可解析）；调用方据此降级，不中断报告。"""


@dataclass
class AiConfig:
    base_url: str
    api_key: str
    model: str


def config_from_env(env: Mapping[str, str]) -> AiConfig | None:
    """三个环境变量缺一（含空白值）即视为未配置，不发起网络请求。"""
    base_url = (env.get(ENV_BASE_URL) or "").strip()
    api_key = (env.get(ENV_API_KEY) or "").strip()
    model = (env.get(ENV_MODEL) or "").strip()
    if not base_url or not api_key or not model:
        return None
    return AiConfig(base_url=base_url, api_key=api_key, model=model)


def default_transport(url: str, api_key: str, payload: dict, timeout: float) -> dict[str, object]:
    """用标准库调用 OpenAI 兼容端点。"""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
    try:
        return json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AiCallError(f"invalid AI endpoint response: {exc}") from exc


def complete(
    config: AiConfig,
    payload: dict,
    *,
    transport: Transport = default_transport,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    attempts: int = 2,
) -> str:
    """发送 chat/completions 请求并返回回复文本；失败按 attempts 重试，耗尽后抛 AiCallError。"""
    last_error: AiCallError | None = None
    for _ in range(max(1, attempts)):
        try:
            response = transport(
                config.base_url.rstrip("/") + "/chat/completions",
                config.api_key,
                payload,
                timeout_seconds,
            )
            content = response["choices"][0]["message"]["content"]
            if content is None:
                raise AiCallError("empty content in AI response")
            return str(content)
        except AiCallError as exc:
            last_error = exc
        except Exception as exc:  # 传输层任何异常都归入调用失败，由调用方降级
            last_error = AiCallError(str(exc) or exc.__class__.__name__)
    # attempts >= 1，循环至少执行一次，last_error 必已赋值
    raise last_error


def chat_content(
    config: AiConfig,
    *,
    system: str,
    user_payload: object,
    transport: Transport = default_transport,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """单轮补全：把 system 与 user 载荷装配为请求体，语义同 complete。"""
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "temperature": 0,
    }
    return complete(config, payload, transport=transport, timeout_seconds=timeout_seconds)
