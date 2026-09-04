"""Narrow local chat-completion adapter."""
from __future__ import annotations

import json
import urllib.error
import urllib.request


def chat(model: str, messages: list[dict], max_tokens: int, timeout: int,
         temperature: float = 0.35, tools: list[dict] | None = None,
         response_format: dict | None = None) -> dict:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "chat_template_kwargs": {"enable_thinking": False},
        "max_tokens": max_tokens,
    }
    if tools is not None:
        payload.update(tools=tools, tool_choice="auto")
    if response_format is not None:
        payload["response_format"] = response_format
    request = urllib.request.Request(
        "http://127.0.0.1:13305/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer lemonade"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)["choices"][0]["message"]
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"local model HTTP {error.code}: {detail}") from error
