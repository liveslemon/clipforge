"""Shared LLM client for ClipForge: structured (Pydantic-validated) calls used by clip selection and proofreading.
Supports OpenAI (default) and Anthropic.
"""
from __future__ import annotations

from typing import Optional, Type, TypeVar
from pydantic import BaseModel

from .config import get_settings

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(Exception):
    pass


class LLMUnavailable(LLMError):
    """No LLM credentials configured — callers fall back to heuristic logic."""


def llm_available() -> bool:
    s = get_settings()
    return bool(s.openai_api_key or s.anthropic_api_key)


def get_llm_provider() -> str:
    s = get_settings()
    if s.openai_api_key:
        return "openai"
    elif s.anthropic_api_key:
        return "anthropic"
    return "none"


def _call_openai(
    system: str,
    user: str,
    schema: Type[T],
    *,
    model: Optional[str] = None,
    max_tokens: int = 16000,
) -> T:
    import openai

    settings = get_settings()
    client = openai.OpenAI(api_key=settings.openai_api_key, max_retries=3)
    target_model = model or settings.openai_model or "gpt-4o-mini"

    try:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})

        response = client.beta.chat.completions.parse(
            model=target_model,
            messages=messages,
            response_format=schema,
            max_tokens=max_tokens,
        )
    except openai.AuthenticationError as e:
        raise LLMError("OpenAI API key was rejected — check OPENAI_API_KEY in .env.") from e
    except openai.RateLimitError as e:
        raise LLMError("OpenAI rate limit hit — retry shortly.") from e
    except openai.BadRequestError as e:
        raise LLMError(f"OpenAI rejected the request: {e.message}") from e
    except openai.APIStatusError as e:
        raise LLMError(f"OpenAI API error {e.status_code}: {e.message}") from e
    except openai.APIConnectionError as e:
        raise LLMError("Could not reach the OpenAI API (network).") from e

    choice = response.choices[0]
    if getattr(choice.message, "refusal", None):
        raise LLMError(f"OpenAI declined this request: {choice.message.refusal}")
    if choice.finish_reason == "length":
        raise LLMError("OpenAI's reply was cut off (max_tokens).")
    if choice.message.parsed is None:
        raise LLMError("OpenAI returned no structured output.")

    return choice.message.parsed


def _call_anthropic(
    system: str,
    user: str,
    schema: Type[T],
    *,
    effort: str = "medium",
    max_tokens: int = 16000,
    model: Optional[str] = None,
) -> T:
    import anthropic

    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=3)
    target_model = model or settings.clipforge_llm_model

    try:
        response = client.beta.messages.parse(
            model=target_model,
            max_tokens=max_tokens,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            output_config={"effort": effort},
            output_format=schema,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.AuthenticationError as e:
        raise LLMError("Anthropic API key was rejected — check ANTHROPIC_API_KEY.") from e
    except anthropic.RateLimitError as e:
        raise LLMError("Anthropic rate limit hit — retry shortly.") from e
    except anthropic.BadRequestError as e:
        raise LLMError(f"Anthropic rejected the request: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"Anthropic API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError("Could not reach the Anthropic API (network).") from e

    if response.stop_reason == "refusal":
        raise LLMError("Claude declined this request.")
    if response.stop_reason == "max_tokens":
        raise LLMError("Claude's reply was cut off (max_tokens).")
    if response.parsed_output is None:
        raise LLMError("Claude returned no structured output.")
    return response.parsed_output


def structured_call(
    system: str,
    user: str,
    schema: Type[T],
    *,
    effort: str = "medium",
    max_tokens: int = 16000,
    model: Optional[str] = None,
) -> T:
    """Invokes structured output using OpenAI (if OPENAI_API_KEY is configured) or Anthropic.

    Raises LLMError on failure or refusal.
    """
    provider = get_llm_provider()
    if provider == "openai":
        return _call_openai(system, user, schema, model=model, max_tokens=max_tokens)
    elif provider == "anthropic":
        return _call_anthropic(system, user, schema, effort=effort, max_tokens=max_tokens, model=model)
    else:
        raise LLMUnavailable("Neither OPENAI_API_KEY nor ANTHROPIC_API_KEY is set in .env.")
