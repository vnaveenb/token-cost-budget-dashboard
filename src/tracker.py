from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import litellm
from litellm.integrations.custom_logger import CustomLogger

from .budget import BudgetExceededError, enforce_budget
from .db import get_conn
from .pricing import calculate_cost

logger = logging.getLogger(__name__)

_DEFAULT_PROJECT_ID: Optional[str] = None
_DEFAULT_USER_ID: Optional[str] = None
_logger_instance: Optional[_UsageLogger] = None


class _UsageLogger(CustomLogger):
    async def async_log_success_event(
        self,
        kwargs: dict,
        response_obj: Any,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, self._write_success, kwargs, response_obj, start_time, end_time
        )

    def _write_success(
        self, kwargs: dict, response_obj: Any, start_time: datetime, end_time: datetime
    ) -> None:
        try:
            usage = getattr(response_obj, "usage", None)
            input_tokens = getattr(usage, "prompt_tokens", 0) or 0
            output_tokens = getattr(usage, "completion_tokens", 0) or 0
            model = kwargs.get("model", "unknown")
            provider = _extract_provider(model, kwargs)
            cost = calculate_cost(model, input_tokens, output_tokens)
            latency_ms = int((end_time - start_time).total_seconds() * 1000)
            meta = (kwargs.get("litellm_params") or {}).get("metadata") or {}
            project_id = meta.get("project_id") or _DEFAULT_PROJECT_ID
            user_id = meta.get("user_id") or _DEFAULT_USER_ID
            endpoint = meta.get("endpoint")
            _insert_usage_log(
                model=model, provider=provider,
                input_tokens=input_tokens, output_tokens=output_tokens,
                cost_usd=cost, latency_ms=latency_ms,
                project_id=project_id, user_id=user_id,
                endpoint=endpoint, status="success", error_msg=None,
            )
        except Exception:
            logger.exception("Failed to log LLM usage")

    async def async_log_failure_event(
        self,
        kwargs: dict,
        response_obj: Any,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, self._write_failure, kwargs, response_obj, start_time, end_time
        )

    def _write_failure(
        self, kwargs: dict, response_obj: Any, start_time: datetime, end_time: datetime
    ) -> None:
        try:
            model = kwargs.get("model", "unknown")
            provider = _extract_provider(model, kwargs)
            latency_ms = int((end_time - start_time).total_seconds() * 1000)
            meta = (kwargs.get("litellm_params") or {}).get("metadata") or {}
            project_id = meta.get("project_id") or _DEFAULT_PROJECT_ID
            user_id = meta.get("user_id") or _DEFAULT_USER_ID
            endpoint = meta.get("endpoint")
            error_msg = str(response_obj) if response_obj else str(kwargs.get("exception", ""))
            _insert_usage_log(
                model=model, provider=provider,
                input_tokens=0, output_tokens=0,
                cost_usd=0.0, latency_ms=latency_ms,
                project_id=project_id, user_id=user_id,
                endpoint=endpoint, status="error", error_msg=error_msg[:500],
            )
        except Exception:
            logger.exception("Failed to log LLM failure")

    # Also handle sync completion calls
    def log_success_event(
        self,
        kwargs: dict,
        response_obj: Any,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        self._write_success(kwargs, response_obj, start_time, end_time)

    def log_failure_event(
        self,
        kwargs: dict,
        response_obj: Any,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        self._write_failure(kwargs, response_obj, start_time, end_time)


def _extract_provider(model: str, kwargs: dict) -> str:
    provider = (kwargs.get("litellm_params") or {}).get("custom_llm_provider")
    if provider:
        return provider
    if "/" in model:
        return model.split("/")[0]
    if any(x in model for x in ("gpt", "o1", "o3")):
        return "openai"
    if "claude" in model:
        return "anthropic"
    if "gemini" in model:
        return "google"
    if "mistral" in model:
        return "mistral"
    return "unknown"


def _insert_usage_log(**fields: Any) -> None:
    conn = get_conn()
    row_id = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO usage_log
           (id, timestamp, model, provider, input_tokens, output_tokens,
            cost_usd, latency_ms, project_id, user_id, endpoint, status, error_msg)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            row_id, ts,
            fields["model"], fields["provider"],
            fields["input_tokens"], fields["output_tokens"],
            fields["cost_usd"], fields["latency_ms"],
            fields.get("project_id"), fields.get("user_id"),
            fields.get("endpoint"), fields["status"], fields.get("error_msg"),
        ),
    )
    conn.commit()


def register_callbacks(
    project_id: Optional[str] = None,
    default_user: Optional[str] = None,
) -> None:
    """Register the usage logger with LiteLLM. Call once at startup."""
    global _logger_instance, _DEFAULT_PROJECT_ID, _DEFAULT_USER_ID
    _DEFAULT_PROJECT_ID = project_id
    _DEFAULT_USER_ID = default_user

    if _logger_instance is None:
        _logger_instance = _UsageLogger()

    if _logger_instance not in litellm.callbacks:
        litellm.callbacks.append(_logger_instance)

    litellm.suppress_debug_info = True


async def tracked_completion(
    model: str,
    messages: list[dict],
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
    endpoint: Optional[str] = None,
    **litellm_kwargs: Any,
) -> Any:
    """Budget-enforcing wrapper around litellm.acompletion.

    Raises BudgetExceededError if a reject-action budget is over its limit.
    """
    effective_project = project_id or _DEFAULT_PROJECT_ID
    effective_user = user_id or _DEFAULT_USER_ID
    enforce_budget(effective_project, effective_user)

    meta = litellm_kwargs.pop("metadata", {}) or {}
    meta.update({
        "project_id": effective_project,
        "user_id": effective_user,
        "endpoint": endpoint,
    })

    return await litellm.acompletion(
        model=model,
        messages=messages,
        metadata=meta,
        **litellm_kwargs,
    )
