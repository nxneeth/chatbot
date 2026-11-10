"""Minimal client for any OpenAI-compatible chat endpoint (Groq, Ollama, OpenRouter, ...)."""
import json
import logging
import re

import requests

from app.config import settings

log = logging.getLogger("edulayne.llm")


class LLMError(RuntimeError):
    pass


def chat(messages, model=None, max_tokens=900, temperature=0.3, json_mode=False):
    if not settings.llm_enabled:
        raise LLMError("No language model configured")
    body = {
        "model": model or settings.LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_completion_tokens": max_tokens,
    }
    if settings.LLM_REASONING_EFFORT:
        body["reasoning_effort"] = settings.LLM_REASONING_EFFORT
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json"}
    if settings.LLM_API_KEY:
        headers["Authorization"] = f"Bearer {settings.LLM_API_KEY}"
    try:
        resp = requests.post(f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions", json=body, headers=headers,
                             timeout=settings.LLM_TIMEOUT)
    except requests.RequestException as exc:
        raise LLMError(f"Model request failed: {exc}") from exc
    if resp.status_code != 200:
        log.warning("LLM error %s: %s", resp.status_code, resp.text[:400])
        raise LLMError(f"Model returned HTTP {resp.status_code}")
    try:
        content = resp.json()["choices"][0]["message"].get("content") or ""
    except (KeyError, IndexError, ValueError) as exc:
        raise LLMError("Unexpected model response") from exc
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
    if not content:
        raise LLMError("Empty model response")
    return content


def chat_json(messages, model=None, max_tokens=300):
    text = chat(messages, model=model or settings.LLM_ROUTER_MODEL, max_tokens=max_tokens, temperature=0, json_mode=True)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise LLMError("Model did not return JSON")
    try:
        return json.loads(m.group())
    except json.JSONDecodeError as exc:
        raise LLMError("Model returned invalid JSON") from exc
