"""
LLM Client Service for Incident Cortex.

Provides async LLM completion with Claude (Anthropic) as primary,
OpenRouter as fallback, with Pydantic validation and Langfuse logging.
"""

import asyncio
import json
import logging
import re
import httpx
from typing import Any, Type, TypeVar
from datetime import datetime

try:
    import anthropic
except ImportError:
    anthropic = None

from pydantic import BaseModel, ValidationError

from app.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

TIMEOUT_SECONDS = 30


class LLMClient:
    """Async LLM client with fallback and validation."""

    def __init__(self):
        self.settings = get_settings()
        self.timeout = TIMEOUT_SECONDS
        self.anthropic_client = None
        self.openrouter_client = httpx.AsyncClient()

        if self.settings.anthropic_api_key:
            if anthropic:
                self.anthropic_client = anthropic.Anthropic(
                    api_key=self.settings.anthropic_api_key
                )

    @staticmethod
    def extract_json(text: str) -> str:
        """Strip markdown code fences and return the JSON substring."""
        # Try ```json ... ``` or ``` ... ```
        match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
        if match:
            return match.group(1)
        # Try bare { ... } or [ ... ]
        match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
        if match:
            return match.group(1)
        return text

    async def call(self, system_prompt: str, user_prompt: str, incident_id: str = "") -> str:
        """Call LLM with system + user prompt, return raw text string."""
        combined = f"{system_prompt}\n\n{user_prompt}"
        try:
            if self.anthropic_client:
                loop = asyncio.get_event_loop()
                response = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: self.anthropic_client.messages.create(
                            model="claude-sonnet-4-6",
                            max_tokens=2048,
                            system=system_prompt,
                            messages=[{"role": "user", "content": user_prompt}],
                        ),
                    ),
                    timeout=self.timeout,
                )
                return response.content[0].text
            else:
                # OpenRouter fallback
                payload = {
                    "model": self.settings.openrouter_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "max_tokens": 2048,
                }
                resp = await self.openrouter_client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.settings.openrouter_api_key}"},
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"LLM call failed: {e}", extra={"incident_id": incident_id})
            raise

    async def complete(
        self,
        prompt: str,
        schema: Type[T],
        incident_id: str = "",
    ) -> T:
        """
        Complete a prompt and parse response into Pydantic model.

        Args:
            prompt: The input prompt
            schema: Target Pydantic model class
            incident_id: Optional incident ID for logging

        Returns:
            Validated Pydantic model instance with _used_fallback flag
        """
        try:
            if self.anthropic_client:
                return await self._complete_with_anthropic(
                    prompt, schema, incident_id
                )
            else:
                logger.info(
                    "No Anthropic API key, using OpenRouter",
                    extra={"incident_id": incident_id},
                )
                return await self._complete_with_openrouter(
                    prompt, schema, incident_id, is_fallback=False
                )
        except (asyncio.TimeoutError, httpx.HTTPStatusError) as e:
            logger.warning(
                f"Primary LLM failed ({type(e).__name__}), switching to fallback",
                extra={"incident_id": incident_id},
            )
            return await self._complete_with_openrouter(
                prompt, schema, incident_id, is_fallback=True
            )

    async def _complete_with_anthropic(
        self,
        prompt: str,
        schema: Type[T],
        incident_id: str,
    ) -> T:
        """Use Claude via Anthropic API."""
        start_time = datetime.now()

        try:
            loop = asyncio.get_event_loop()
            response = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self.anthropic_client.messages.create(
                        model="claude-sonnet-4-6",
                        max_tokens=2048,
                        messages=[
                            {
                                "role": "user",
                                "content": prompt,
                            }
                        ],
                    ),
                ),
                timeout=self.timeout,
            )

            raw_text = response.content[0].text
            latency_ms = (datetime.now() - start_time).total_seconds() * 1000

            result = await self._parse_with_retry(raw_text, schema)
            result._used_fallback = False

            # Log to Langfuse
            self._log_langfuse(
                model="claude-sonnet-4-6",
                prompt_tokens=response.usage.input_tokens,
                completion_tokens=response.usage.output_tokens,
                latency_ms=latency_ms,
                incident_id=incident_id,
                event_type="llm_call",
            )

            return result

        except asyncio.TimeoutError as e:
            logger.error(
                "Anthropic API timeout",
                extra={"incident_id": incident_id},
            )
            raise

    async def _complete_with_openrouter(
        self,
        prompt: str,
        schema: Type[T],
        incident_id: str,
        is_fallback: bool = False,
    ) -> T:
        """Use fallback model via OpenRouter API."""
        start_time = datetime.now()

        try:
            headers = {
                "Authorization": f"Bearer {self.settings.openrouter_api_key}",
                "HTTP-Referer": "incident-cortex",
            }

            model = (
                self.settings.openrouter_model
                or "meta-llama/llama-2-70b-chat"
            )

            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 2048,
            }

            response = await asyncio.wait_for(
                self.openrouter_client.post(
                    "https://openrouter.io/api/v1/chat/completions",
                    json=payload,
                    headers=headers,
                ),
                timeout=self.timeout,
            )

            response.raise_for_status()
            data = response.json()

            raw_text = data["choices"][0]["message"]["content"]
            latency_ms = (datetime.now() - start_time).total_seconds() * 1000

            result = await self._parse_with_retry(raw_text, schema)
            result._used_fallback = True

            # Log to Langfuse
            self._log_langfuse(
                model=model,
                prompt_tokens=data.get("usage", {}).get("prompt_tokens", 0),
                completion_tokens=data.get("usage", {}).get(
                    "completion_tokens", 0
                ),
                latency_ms=latency_ms,
                incident_id=incident_id,
                event_type="llm_fallback" if is_fallback else "llm_call",
            )

            return result

        except asyncio.TimeoutError as e:
            logger.error(
                "OpenRouter API timeout",
                extra={"incident_id": incident_id},
            )
            raise

    async def _parse_with_retry(
        self,
        raw: str,
        schema: Type[T],
        max_retries: int = 2,
    ) -> T:
        """
        Parse LLM response into Pydantic model with retry on validation error.

        Args:
            raw: Raw LLM response text
            schema: Target Pydantic model class
            max_retries: Maximum retry attempts

        Returns:
            Validated Pydantic model instance
        """
        json_str = raw
        if "```json" in raw:
            start = raw.find("```json") + 7
            end = raw.find("```", start)
            json_str = raw[start:end].strip()
        elif "```" in raw:
            start = raw.find("```") + 3
            end = raw.find("```", start)
            json_str = raw[start:end].strip()

        for attempt in range(max_retries):
            try:
                data = json.loads(json_str)
                return schema(**data)
            except (json.JSONDecodeError, ValidationError) as e:
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Parsing attempt {attempt + 1} failed, retrying: {e}"
                    )
                    # In a real system, we'd re-prompt with error feedback
                    # For now, just retry with better error feedback
                    continue
                else:
                    logger.error(
                        f"Failed to parse after {max_retries} attempts: {e}"
                    )
                    raise

    def _log_langfuse(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        incident_id: str = "",
        event_type: str = "llm_call",
    ) -> None:
        """Log LLM call to Langfuse (placeholder for actual integration)."""
        logger.info(
            f"{event_type}: {model}",
            extra={
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "latency_ms": latency_ms,
                "incident_id": incident_id,
                "event_type": event_type,
            },
        )

    async def close(self) -> None:
        """Close HTTP client."""
        await self.openrouter_client.aclose()


# Singleton instance
_llm_client: LLMClient | None = None


async def get_llm_client() -> LLMClient:
    """Get or create LLM client singleton."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
