"""LLM provider configuration for FleetCopilot.

Supports a local Llama 3 model (via an OpenAI-compatible endpoint, e.g.
Ollama) and Claude via the Anthropic API or OpenRouter, per the
multi-provider strategy in CLAUDE.md.
"""

from __future__ import annotations

import os
from enum import Enum
from typing import Any


class LLMProvider(str, Enum):
    LOCAL_LLAMA = "local_llama"
    CLAUDE_ANTHROPIC = "claude_anthropic"
    CLAUDE_OPENROUTER = "claude_openrouter"
    GROQ = "groq"
    LLAMA_API = "llama_api"


def get_chat_model(provider: LLMProvider, **overrides: Any):
    """Return a configured LangChain chat model for the given provider.

    Provider-specific packages are imported lazily so this module stays
    importable without every optional dependency installed.
    """
    if provider is LLMProvider.LOCAL_LLAMA:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            base_url=os.environ.get("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1"),
            api_key="not-needed",
            model=overrides.pop("model", os.environ.get("LOCAL_LLM_MODEL", "llama3")),
            **overrides,
        )

    if provider is LLMProvider.CLAUDE_ANTHROPIC:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            model=overrides.pop("model", "claude-sonnet-5"),
            **overrides,
        )

    if provider is LLMProvider.CLAUDE_OPENROUTER:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            base_url="https://openrouter.ai/api/v1",
            # .env historically spells it OPEN_ROUTER_API_KEY; accept both.
            api_key=os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPEN_ROUTER_API_KEY"),
            model=overrides.pop("model", os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-5")),
            # OpenRouter reserves credit for the full max output up front and rejects (402) a request
            # it can't cover; the model default is tens of thousands of tokens. Chat turns need ~1k.
            max_tokens=overrides.pop("max_tokens", int(os.environ.get("OPENROUTER_MAX_TOKENS", "1500"))),
            **overrides,
        )

    if provider is LLMProvider.GROQ:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=os.environ.get("GROQ_API_KEY"),
            model=overrides.pop("model", os.environ.get("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")),
            **overrides,
        )

    if provider is LLMProvider.LLAMA_API:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            base_url=os.environ.get("LLAMA_API_BASE_URL", "https://api.llama.com/compat/v1"),
            api_key=os.environ.get("LLAMA_API_KEY"),
            model=overrides.pop("model", os.environ.get("LLAMA_API_MODEL", "Llama-4-Maverick-17B-128E-Instruct-FP8")),
            **overrides,
        )

    raise ValueError(f"Unknown LLM provider: {provider}")
