"""BYOK 客户端：OpenAI 兼容端点的受控调用（自 optimize/advisor.py 收拢，行为不变）。

红线落地（ADR-0009 design §4）：
- 配置三元组（MOUDO_AI_BASE_URL / MOUDO_AI_API_KEY / MOUDO_AI_MODEL）缺一即视为
  未配置，不发起任何网络请求；
- 发送载荷由调用方构造，仅含 SQL 文本与 schema 元数据，绝不含数据行；
- transport 注入可测：测试零真实网络。
"""

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
    """从模型回复提取 JSON 数组（结构化输出约定的提取层）；无数组返回 None。"""
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
    """三元组缺一即未配置（含空白值）：未配置 = 零网络请求。"""
    base_url = (env.get(ENV_BASE_URL) or "").strip()
    api_key = (env.get(ENV_API_KEY) or "").strip()
    model = (env.get(ENV_MODEL) or "").strip()
    if not base_url or not api_key or not model:
        return None
    return AiConfig(base_url=base_url, api_key=api_key, model=model)


def default_transport(url: str, api_key: str, payload: dict, timeout: float) -> dict[str, object]:
    """OpenAI 兼容端点调用（stdlib，无额外依赖；未配置时永不执行）。"""
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
    """发送完整 chat/completions 请求体：返回助手回复文本；失败抛 AiCallError。

    请求体由调用方（车道模块）构造——提示词是车道资产，客户端不拼装业务语义。
    attempts 是传输层尝试总次数：默认 2 次，吸收一过性通道故障（连接重置/响应半途
    截断——首版 BYOK 实测出现过一次）；持续性失败（鉴权/端点错误）多花一次请求后
    原样抛出，由调用方降级。如未来出现高频限流再引入退避，不预设。
    """
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
        except Exception as exc:  # fail-safe 边界：传输层任何异常（含 http.client.HTTPException 族）都归入调用失败
            last_error = AiCallError(str(exc) or exc.__class__.__name__)
    # attempts >= 1 保证循环至少执行一轮，last_error 必已赋值
    raise last_error


def chat_content(
    config: AiConfig,
    *,
    system: str,
    user_payload: object,
    transport: Transport = default_transport,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """单轮补全便捷入口（system + user 载荷自动装配为请求体），语义同 complete。"""
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "temperature": 0,
    }
    return complete(config, payload, transport=transport, timeout_seconds=timeout_seconds)
