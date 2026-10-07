"""Optional LLM helper shared by ingest.py (keywords) and index.py (Q&A).

Supports Groq and Google Gemini, auto-detected from environment variables
(or a .env file). Everything degrades gracefully when no key is set.
Model names change often, so they can be overridden with GROQ_MODEL /
GEMINI_MODEL instead of editing code.
"""
from __future__ import annotations

import os

GROQ_MODEL_DEFAULT = "llama-3.1-8b-instant"
GEMINI_MODEL_DEFAULT = "gemini-2.5-flash"

_client = None          # (provider, client) once resolved, or False if none available
last_error: str | None = None   # most recent failure, so callers can report it


def get_client():
    """Return (provider, client) if an API key is configured, else None."""
    global _client
    if _client is not None:
        return _client or None
    try:
        from dotenv import load_dotenv
        from config import BASE_DIR
        load_dotenv(BASE_DIR / ".env")
    except ImportError:
        pass

    groq_key = os.environ.get("GROQ_API_KEY")
    google_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if groq_key:
        try:
            from groq import Groq
            _client = ("groq", Groq(api_key=groq_key))
            return _client
        except Exception as exc:  # noqa: BLE001 - missing package or bad key
            _set_error(f"groq unavailable: {exc}")
    if google_key:
        try:
            from google import genai
            _client = ("gemini", genai.Client(api_key=google_key))
            return _client
        except Exception as exc:  # noqa: BLE001
            _set_error(f"gemini unavailable: {exc}")
    _client = False
    return None


def _set_error(msg: str) -> None:
    global last_error
    last_error = msg


def provider_name() -> str | None:
    c = get_client()
    return c[0] if c else None


def complete(prompt: str, max_tokens: int = 300, temperature: float = 0.2) -> str | None:
    """Send a prompt; return the reply text, or None on any failure (see last_error)."""
    c = get_client()
    if not c:
        return None
    provider, client = c
    try:
        if provider == "groq":
            resp = client.chat.completions.create(
                model=os.environ.get("GROQ_MODEL", GROQ_MODEL_DEFAULT),
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature, max_tokens=max_tokens)
            return (resp.choices[0].message.content or "").strip() or None
        resp = client.models.generate_content(
            model=os.environ.get("GEMINI_MODEL", GEMINI_MODEL_DEFAULT), contents=prompt)
        return (getattr(resp, "text", "") or "").strip() or None
    except Exception as exc:  # noqa: BLE001 - network, quota, bad model name...
        _set_error(f"{provider} request failed: {exc}")
        return None
