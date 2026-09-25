"""Model-generated presentation for internal notifications."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from ecosystem import cli
from ecosystem.inference import request as inference_request
from ecosystem.managed_inference import request as managed_request
from ecosystem.resource_control import active_chat_model


CONTROL_ROLE = Path(__file__).resolve().parents[1] / "roles/_control-plane.md"


def humanize_notification(raw: str, history: list[dict[str, str]] | None = None,
                          inference_context: dict | None = None) -> str:
    model = active_chat_model(os.environ.get("AGENT_TELEGRAM_MODEL", "Qwen3.5-4B-GGUF"))
    system = f"""{CONTROL_ROLE.read_text(encoding='utf-8')}

Rewrite an internal agent notification as one concise Telegram message to David.
Preserve consequential facts, requested decisions, failures, and useful results.
Remove internal IDs, log paths, tool chatter, JSON, and queue mechanics. Preserve
the agent's name naturally. Never infer success from process exit. Ask a question
only when the source explicitly requires David's decision. Never add a generic
follow-up invitation. Output only the message."""
    messages = [{"role": "system", "content": system}, *((history or [])[-8:]),
                {"role": "user", "content": raw}]
    assistant = (
        inference_request({
            **inference_context, "messages": messages, "temperature": 0.4,
            "timeout": None,
        }, cli.ROOT, __import__("time").monotonic)
        if inference_context is not None else
        managed_request(model, messages, 512, timeout=None, temperature=0.4,
                        root=cli.ROOT, control=True)
    )
    return sanitize_notification(assistant["content"])


def sanitize_notification(message: str) -> str:
    text = message.strip()
    tails = (
        r"\s+Want to (?:dive into|chat about|go over|discuss)[^?]*\?\s*$",
        r"\s+Want me to [^?]*\?\s*$",
        r"\s+Would you like me to [^?]*\?\s*$",
        r"\s+(?:Or )?[Ss]hould we [^?]*\?\s*$",
        r"\s+Let me know if [^.?!]*[.?!]\s*$",
    )
    for tail in tails:
        text = re.sub(tail, "", text, flags=re.IGNORECASE)
    return text.strip()
