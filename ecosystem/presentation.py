"""Model-generated presentation for internal notifications."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path


CONTROL_ROLE = Path(__file__).resolve().parents[1] / "roles/_control-plane.md"
WORKSPACE_INSTRUCTIONS = Path.home() / "AGENTS.md"


def humanize_notification(raw: str, history: list[dict[str, str]] | None = None) -> str:
    model = os.environ.get("AGENT_TELEGRAM_MODEL", "Qwen3.8-27B-GGUF")
    system = f"""{WORKSPACE_INSTRUCTIONS.read_text(encoding='utf-8')}

{CONTROL_ROLE.read_text(encoding='utf-8')}

Rewrite an internal agent notification as one concise Telegram message to David.
Preserve consequential facts, requested decisions, failures, and useful results.
Remove internal IDs, log paths, tool chatter, JSON, and queue mechanics. Preserve
the agent's name naturally. Never infer success from process exit. Ask a question
only when the source explicitly requires David's decision. Never add a generic
follow-up invitation. Output only the message."""
    messages = [{"role": "system", "content": system}, *((history or [])[-8:]),
                {"role": "user", "content": raw}]
    body = json.dumps({"model": model, "messages": messages, "temperature": 0.4,
                       "chat_template_kwargs": {"enable_thinking": False},
                       "max_tokens": 700}).encode()
    request = urllib.request.Request("http://127.0.0.1:13305/v1/chat/completions",
                                     data=body, headers={"Content-Type": "application/json", "Authorization": "Bearer lemonade"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return sanitize_notification(json.load(response)["choices"][0]["message"]["content"])
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"notification model HTTP {error.code}: {detail}") from error


def sanitize_notification(message: str) -> str:
    text = message.strip()
    tails = (
        r"\s+Want to (?:dive into|chat about|go over|discuss)[^?]*\?\s*$",
        r"\s+Want me to [^?]*\?\s*$",
        r"\s+(?:Or )?[Ss]hould we [^?]*\?\s*$",
        r"\s+Let me know if [^.?!]*[.?!]\s*$",
    )
    for tail in tails:
        text = re.sub(tail, "", text, flags=re.IGNORECASE)
    return text.strip()
