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
            model=os.environ.get("LOCAL_LLM_MODEL", "llama3"),
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
            api_key=os.environ.get("OPENROUTER_API_KEY"),
            model=overrides.pop("model", "anthropic/claude-sonnet-5"),
            **overrides,
        )

    raise ValueError(f"Unknown LLM provider: {provider}")
