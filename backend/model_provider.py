import os
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

from openai import AsyncOpenAI


DEFAULT_MODEL_BASE_URL = os.getenv("MODEL_BASE_URL", "https://api.deepseek.com").rstrip("/")


class ModelProvider(Protocol):
    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float = 0.3,
    ) -> str: ...


@dataclass(frozen=True)
class OpenAICompatibleProvider:
    api_key: str
    model: str
    base_url: str = DEFAULT_MODEL_BASE_URL

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float = 0.3,
    ) -> str:
        if not self.api_key:
            raise RuntimeError("模型 API Key 未配置")
        client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url.rstrip("/"))
        response = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return (response.choices[0].message.content or "").strip()


def create_model_provider(api_key: str, model: str, base_url: str | None = None) -> ModelProvider:
    url = (base_url or DEFAULT_MODEL_BASE_URL).strip().rstrip("/")
    parsed = urlparse(url)
    local_http = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not local_http:
        raise ValueError("模型 Base URL 必须使用 HTTPS；本机 localhost 可使用 HTTP")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("模型 Base URL 格式无效，不能包含凭据")
    return OpenAICompatibleProvider(api_key=api_key, model=model, base_url=url)
