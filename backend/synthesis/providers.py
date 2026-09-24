"""Multi-provider LLM abstraction with automatic fallback chain.

All three free providers support the OpenAI-compatible chat completions API,
so we use the `openai` SDK with different base_url / api_key / model settings.

Priority chain (first available wins):
  1. Groq   — free cloud, very fast, openai/gpt-oss-120b (writer) / gpt-oss-20b (short summaries)
  2. Gemini — free cloud, gemini-flash-lite-latest (PDB's independent Editor-in-Chief)
  3. Ollama — local, no key needed, fully private (slow on weak hardware)
  4. Stub   — deterministic extractive fallback, always works

Set keys via environment variables:
  GROQ_API_KEY    — free at https://console.groq.com/keys
  GEMINI_API_KEY  — free at https://aistudio.google.com/apikey
  OLLAMA_MODEL    — e.g. "qwen2.5:1.5b" (run `ollama pull qwen2.5:1.5b` first)
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("synthesis.providers")


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key: str | None
    tldr_model: str
    analysis_model: str
    available: bool


def _check_ollama() -> bool:
    """Check if Ollama is running locally."""
    import httpx
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=3.0)
        return r.status_code == 200
    except Exception:
        return False


def _ollama_model() -> str:
    """Pick the smallest available model, or default to qwen2.5:1.5b."""
    import httpx
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=3.0)
        models = r.json().get("models", [])
        if not models:
            return os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")
        # Prefer small models for weak hardware
        preferred = ["qwen2.5:1.5b", "qwen2.5:0.5b", "llama3.2:1b", "phi3:mini", "gemma2:2b"]
        installed = {m["name"] for m in models}
        for p in preferred:
            if p in installed:
                return p
        # Fall back to whatever is installed (smallest first by size)
        models.sort(key=lambda m: m.get("size", 0))
        return models[0]["name"] if models else "qwen2.5:1.5b"
    except Exception:
        return os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")


def get_providers() -> list[ProviderConfig]:
    """Build the provider chain in priority order."""
    providers: list[ProviderConfig] = []

    # 1. Groq
    groq_key = os.getenv("GROQ_API_KEY")
    providers.append(ProviderConfig(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        api_key=groq_key,
        tldr_model="openai/gpt-oss-20b",
        analysis_model="openai/gpt-oss-120b",
        available=bool(groq_key),
    ))

    # 2. Gemini (OpenAI-compatible endpoint)
    gemini_key = os.getenv("GEMINI_API_KEY")
    providers.append(ProviderConfig(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key=gemini_key,
        # Flash-Lite: the free tier allows far more requests/day than Flash (which is capped at 20/day).
        # "-latest" alias survives model retirements.
        tldr_model="gemini-flash-lite-latest",
        analysis_model="gemini-flash-lite-latest",
        available=bool(gemini_key),
    ))

    # 3. Ollama (local, no key)
    ollama_up = _check_ollama()
    model = _ollama_model() if ollama_up else os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b")
    providers.append(ProviderConfig(
        name="ollama",
        base_url="http://localhost:11434/v1",
        api_key="ollama",  # Ollama ignores the key but the SDK requires one
        tldr_model=model,
        analysis_model=model,
        available=ollama_up,
    ))

    return providers


def get_active_provider() -> ProviderConfig | None:
    """Return the first available provider, or None (stub mode)."""
    for p in get_providers():
        if p.available:
            log.info("LLM provider: %s (tldr=%s, analysis=%s)", p.name, p.tldr_model, p.analysis_model)
            return p
    log.info("No LLM provider available — using deterministic stub")
    return None


def get_provider(name: str) -> ProviderConfig | None:
    """A specific provider by name, if it is available."""
    for p in get_providers():
        if p.name == name and p.available:
            return p
    return None


def validate(provider: ProviderConfig) -> list[str]:
    """Return problems (e.g. retired model names). Empty list = OK.

    Free providers retire models without warning, and a model can be *listed*
    yet refused (Gemini did this). So we make one tiny real call per model;
    a run then fails loudly instead of silently publishing placeholder text.
    """
    problems = []
    for m in {provider.tldr_model, provider.analysis_model}:
        try:
            chat(provider, m, "Reply with the single word OK.", "ping", max_retries=1)
        except Exception as e:
            status = getattr(e, "status_code", None)
            if status in (429, 500, 502, 503, 504) and "quota" not in str(e).lower():
                log.warning("%s/%s busy at startup (%s) — key accepted; per-story retries/backup will handle it",
                            provider.name, m, status)
                continue
            problems.append(f"{provider.name}: model '{m}' unusable ({type(e).__name__}: {str(e)[:120]})")
    return problems


_RETRY_RE = re.compile(r"try again in ([0-9.]+)(ms|s|m)", re.I)


def _retry_delay(err: Exception, attempt: int) -> float:
    m = _RETRY_RE.search(str(err))
    if m:
        v = float(m.group(1))
        return {"ms": v / 1000, "s": v, "m": v * 60}[m.group(2).lower()] + 1.0
    return min(60.0, 5.0 * (2 ** attempt))


def chat(provider: ProviderConfig, model: str, system: str, user: str, *, json_mode: bool = False,
         max_retries: int = 5, max_tokens: int | None = None) -> str:
    """Call a provider's chat completion endpoint, retrying on rate limits / transient errors."""
    from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError
    client = OpenAI(base_url=provider.base_url, api_key=provider.api_key, timeout=120, max_retries=0)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
    }
    if max_tokens:
        kwargs["max_tokens"] = max_tokens
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if provider.name in ("groq", "gemini"):
        kwargs["reasoning_effort"] = "low"   # keeps free-tier token use down
    for attempt in range(max_retries + 1):
        try:
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except (RateLimitError, APIConnectionError) as e:
            err = e
        except APIStatusError as e:
            if e.status_code not in (408, 409, 429, 500, 502, 503, 504):
                raise
            err = e
        if attempt == max_retries:
            raise err
        delay = _retry_delay(err, attempt)
        log.info("%s rate-limited/transient error; retrying in %.1fs", provider.name, delay)
        time.sleep(delay)
    return ""
