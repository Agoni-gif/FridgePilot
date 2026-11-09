"""OpenAI 兼容聊天接口封装：请求 JSON 输出并解析。"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.common.config import Settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """LLM 调用失败。"""


@dataclass
class LLMJsonResult:
    """模型返回的 JSON 与可选 reasoning。"""

    data: dict[str, Any]
    reasoning: str | None = None


class LLMProvider:
    """调用配置中的 chat completions 端点。"""

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
        purpose: str = "chat_json",  # 日志用途标签
    ) -> LLMJsonResult:
        """调用 chat completions，要求 JSON 对象输出；临时错误最多重试一次。"""
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
                message = data["choices"][0]["message"]
                content = message.get("content") or ""
                usage = data.get("usage") or {}
                logger.info(
                    "LLM purpose=%s ok model=%s elapsed_ms=%s prompt_tokens=%s completion_tokens=%s",
                    purpose,
                    self.model,
                    elapsed_ms,
                    usage.get("prompt_tokens"),
                    usage.get("completion_tokens"),
                )
                parsed = self._parse_json(content)
                reasoning = self._collect_reasoning(message, parsed)
                if isinstance(parsed, dict):
                    parsed.pop("thinking", None)
                if not isinstance(parsed, dict):
                    raise LLMError("LLM returned non-object JSON")
                return LLMJsonResult(data=parsed, reasoning=reasoning)
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
    def _collect_reasoning(message: dict[str, Any], parsed: Any) -> str | None:
        """合并 API reasoning_content 与 JSON 内 thinking 字段。"""
        parts: list[str] = []
        api_reasoning = message.get("reasoning_content")
        if isinstance(api_reasoning, str) and api_reasoning.strip():
            parts.append(api_reasoning.strip())
        if isinstance(parsed, dict):
            field = parsed.get("thinking")
            if isinstance(field, str) and field.strip():
                parts.append(field.strip())
        if not parts:
            return None
        # 两者都有时优先保留 API 思维链，JSON thinking 作补充
        return "\n\n".join(parts)

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        """解析模型 content：支持去掉 markdown 代码围栏。"""
        text = content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return json.loads(text)
