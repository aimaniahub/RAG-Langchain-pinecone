"""LangChain + OpenRouter chat chain with retries (Phase 3)."""

from __future__ import annotations

import time
from typing import Any

from app.config import settings
from app.core.exceptions import NotConfiguredError, UpstreamError
from app.core.logging import get_logger
from app.rag.prompts import format_qa_prompt, get_system_prompt

logger = get_logger("rag.chains")


def build_llm(model: str | None = None) -> Any:
    """Build ChatOpenAI pointed at OpenRouter."""
    if not settings.is_openrouter_configured:
        raise NotConfiguredError("OpenRouter")

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model or settings.openrouter_model,
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        temperature=settings.llm_temperature,
        timeout=settings.openrouter_timeout_seconds,
        max_retries=0,  # we handle retries ourselves
        default_headers={
            "HTTP-Referer": settings.openrouter_site_url or "http://localhost",
            "X-Title": settings.openrouter_app_name,
        },
    )


def _is_retryable(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    if "ratelimit" in name or "429" in msg or "rate" in msg and "limit" in msg:
        return True
    if "timeout" in name or "timeout" in msg:
        return True
    if "503" in msg or "502" in msg or "529" in msg:
        return True
    return False


def _messages(question: str, context: str) -> list[Any]:
    from langchain_core.messages import HumanMessage, SystemMessage

    user_content = format_qa_prompt(context=context, question=question)
    return [
        SystemMessage(content=get_system_prompt()),
        HumanMessage(content=user_content),
    ]


def _content_to_text(content: Any) -> str:
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
            else:
                parts.append(str(block))
        return "\n".join(parts).strip()
    return str(content).strip() if content is not None else ""


def run_qa(question: str, context: str, model: str | None = None) -> str:
    """Invoke OpenRouter with grounded context; return answer text."""
    if not context.strip():
        return (
            "I could not find relevant information in the company knowledge base "
            "for this question."
        )

    llm = build_llm(model=model)
    messages = _messages(question, context)

    attempts = max(1, settings.openrouter_max_retries + 1)
    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = llm.invoke(messages)
            text = _content_to_text(getattr(response, "content", None))
            if text:
                return text
            return str(response).strip()
        except NotConfiguredError:
            raise
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < attempts and _is_retryable(exc):
                delay = min(8.0, 1.5 ** attempt)
                logger.warning(
                    "OpenRouter retry attempt=%s/%s delay=%.1fs err=%s",
                    attempt,
                    attempts,
                    delay,
                    str(exc)[:160],
                )
                time.sleep(delay)
                continue
            logger.exception("OpenRouter LLM call failed")
            raise UpstreamError(
                f"LLM provider failed: {exc}",
                provider="openrouter",
            ) from exc

    raise UpstreamError(
        f"LLM provider failed after retries: {last_exc}",
        provider="openrouter",
    )


def stream_qa(question: str, context: str, model: str | None = None):
    """Yield text chunks from OpenRouter streaming response."""
    if not context.strip():
        yield (
            "I could not find relevant information in the company knowledge base "
            "for this question."
        )
        return

    llm = build_llm(model=model)
    messages = _messages(question, context)
    try:
        for chunk in llm.stream(messages):
            text = _content_to_text(getattr(chunk, "content", None))
            if text:
                yield text
    except Exception as exc:  # noqa: BLE001
        logger.exception("OpenRouter stream failed")
        raise UpstreamError(
            f"LLM stream failed: {exc}",
            provider="openrouter",
        ) from exc
