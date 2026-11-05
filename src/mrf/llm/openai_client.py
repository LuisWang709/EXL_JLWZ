"""OpenAI-compatible provider: Azure OpenAI, OpenAI, GitHub Models (same SDK)."""

from __future__ import annotations

import json
import os
from typing import Any

import openai
from pydantic import BaseModel

from mrf.config import get_policy
from mrf.llm.base import BaseLLM, ChatMessage, FatalLLMError, RawCompletion, TransientLLMError

GITHUB_MODELS_URL = "https://models.inference.ai.azure.com"


def _retry_after(exc: openai.APIStatusError) -> float | None:
    try:
        value = exc.response.headers.get("retry-after")
        return float(value) if value else None
    except (AttributeError, ValueError):
        return None


class OpenAICompatLLM(BaseLLM):
    def __init__(self, provider: str, sdk: openai.AsyncOpenAI | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.provider = provider
        timeout = float(get_policy()["retries"]["llm_transient"].get("timeout_s", 60))
        self.sdk = sdk or self._make_sdk(provider, timeout)

    @staticmethod
    def _make_sdk(provider: str, timeout: float) -> openai.AsyncOpenAI:
        # max_retries=0: the SDK's own retries would stack on top of our 1s/2s/4s policy.
        if provider == "azure_openai":
            endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
            version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21")
            key = os.environ.get("AZURE_OPENAI_API_KEY")
            if key:
                return openai.AsyncAzureOpenAI(
                    azure_endpoint=endpoint, api_version=version, api_key=key, max_retries=0, timeout=timeout
                )
            # cloud: managed identity, no key anywhere (needs the 'azure' extra)
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider

            provider_fn = get_bearer_token_provider(
                DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
            )
            return openai.AsyncAzureOpenAI(
                azure_endpoint=endpoint,
                api_version=version,
                azure_ad_token_provider=provider_fn,
                max_retries=0,
                timeout=timeout,
            )
        if provider == "github_models":
            return openai.AsyncOpenAI(
                base_url=os.environ.get("OPENAI_BASE_URL") or GITHUB_MODELS_URL,
                api_key=os.environ.get("GITHUB_TOKEN") or os.environ.get("OPENAI_API_KEY", ""),
                max_retries=0,
                timeout=timeout,
            )
        return openai.AsyncOpenAI(
            base_url=os.environ.get("OPENAI_BASE_URL") or None,
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            max_retries=0,
            timeout=timeout,
        )

    async def _complete(
        self,
        *,
        role: str,
        model: str,
        messages: list[ChatMessage],
        json_schema: type[BaseModel] | None,
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int | None,
    ) -> RawCompletion:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [m.to_openai() for m in messages],
            "temperature": temperature,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if tools:
            kwargs["tools"] = tools
        elif json_schema is not None:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": json_schema.__name__, "schema": json_schema.model_json_schema()},
            }
        try:
            resp = await self.sdk.chat.completions.create(**kwargs)
        except openai.RateLimitError as exc:
            raise TransientLLMError("rate_limit", str(exc), _retry_after(exc)) from exc
        except (openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError) as exc:
            raise TransientLLMError("timeout", str(exc)) from exc
        except openai.APIStatusError as exc:
            raise FatalLLMError(f"{exc.status_code}: {exc}") from exc

        choice = resp.choices[0]
        tool_calls = [
            {"id": tc.id, "name": tc.function.name, "arguments": json.loads(tc.function.arguments or "{}")}
            for tc in (choice.message.tool_calls or [])
            if getattr(tc, "function", None) is not None
        ]
        usage = resp.usage
        return RawCompletion(
            text=choice.message.content or "",
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            model=resp.model or model,
            tool_calls=tool_calls,
        )
