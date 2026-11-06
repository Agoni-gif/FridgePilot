from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from app.common.config import Settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Raised when the LLM provider fails."""


class LLMProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = settings.llm_base_url.rstrip("/")
        self.api_key = settings.llm_api_key
        self.model = settings.llm_model
        self.timeout = settings.request_timeout_seconds

    async def chat_json(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.2,
        purpose: str = "chat_json",
    ) -> dict[str, Any]:
        if not self.api_key:
            raise LLMError("LLM_API_KEY is not configured")

        payload = {
            "model": self.model,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        last_error: Exception | None = None
        for attempt in range(2):
            started = time.perf_counter()
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        f"{self.base_url}/v1/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                elapsed_ms = int((time.perf_counter() - started) * 1000)
                if resp.status_code >= 500 or resp.status_code == 429:
                    raise LLMError(f"LLM temporary error: HTTP {resp.status_code}")
                if resp.status_code >= 400:
                    detail = resp.text[:300]
                    logger.warning(
                        "LLM purpose=%s HTTP %s elapsed_ms=%s body=%s",
                        purpose,
                        resp.status_code,
                        elapsed_ms,
                        detail,
                    )
                    raise LLMError(f"LLM request failed: HTTP {resp.status_code}: {detail}")
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage") or {}
                logger.info(
                    "LLM purpose=%s ok model=%s elapsed_ms=%s prompt_tokens=%s completion_tokens=%s",
                    purpose,
                    self.model,
                    elapsed_ms,
                    usage.get("prompt_tokens"),
                    usage.get("completion_tokens"),
                )
                return self._parse_json(content)
            except (httpx.TimeoutException, httpx.TransportError, LLMError) as exc:
                last_error = exc
                logger.warning(
                    "LLM purpose=%s attempt=%s failed: %s",
                    purpose,
                    attempt + 1,
                    exc,
                )
                if attempt == 0 and isinstance(
                    exc, (httpx.TimeoutException, httpx.TransportError, LLMError)
                ):
                    if isinstance(exc, LLMError) and "temporary" not in str(exc):
                        break
                    continue
                break
            except (KeyError, IndexError, json.JSONDecodeError) as exc:
                last_error = exc
                logger.warning("LLM purpose=%s parse error: %s", purpose, exc)
                break

        raise LLMError(f"LLM call failed: {last_error}")

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return json.loads(text)
