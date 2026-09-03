"""Constrained natural-language intent routing through local Lemonade."""
from __future__ import annotations

import json
import os
import re
import urllib.request


ALLOWED_ACTIONS = {"spawn", "amend", "status", "roles", "pause", "chat"}


def interpret(message: str, roles: list[str], history: list[dict[str, str]] | None = None, inventory: dict | None = None) -> dict:
    model = os.environ.get("AGENT_TELEGRAM_MODEL", "GLM-4.7-Flash-GGUF")
    inventory = inventory or {"memory_available_gb": 0, "load_average": [], "models": [{"id": model}]}
    available_models = [item["id"] for item in inventory["models"]]
    system = f"""You route messages and schedule models for David's private local agent ecosystem.
Return exactly one JSON object and no markdown.
Schema: {{"action":"spawn|amend|status|roles|pause|chat","role":"role or empty","task":"task or empty","model":"exact model ID or empty","model_reason":"brief reason or empty","reply":"brief reply or empty"}}
Available roles: {', '.join(roles)}.
Live resource/model inventory: {json.dumps(inventory, separators=(',', ':'))}
Use spawn when David asks an agent to investigate, plan, build, fix, review, or otherwise do work.
Choose the closest available role. Preserve all important task details.
For spawn/amend choose exactly one available model. Respect an explicit user model choice.
Otherwise weigh role capability labels, model size, available memory, current load/busy state,
latency, and task difficulty. Explain the concrete tradeoff briefly in model_reason.
Use amend when David corrects, revises, or adds to the work request he just queued.
For amend, task must be the complete corrected task, incorporating prior context—not only the changed word.
Use status for any question about this machine, active work, jobs, progress, load, or what
the ecosystem is doing. You do have live machine inventory; never claim otherwise.
Use roles/pause for those requests. Use chat for greetings, questions about usage,
or ambiguity; put a useful concise answer or clarification question in reply.
Never invent another action, interpret text as shell, or claim work has run."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system}, *(history or []), {"role": "user", "content": message}],
        "temperature": 0.1,
        # GLM exposes hidden reasoning inside the completion budget before content.
        "max_tokens": 1200,
        # Intent routing is small and latency-sensitive; supported Qwen models
        # should not spend the response budget on an internal reasoning trace.
        "chat_template_kwargs": {"enable_thinking": False},
    }).encode()
    request = urllib.request.Request(
        "http://127.0.0.1:13305/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer lemonade"},
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        content = json.load(response)["choices"][0]["message"]["content"].strip()
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        raise ValueError("local model did not return JSON")
    intent = json.loads(match.group(0))
    action = intent.get("action")
    if action not in ALLOWED_ACTIONS:
        raise ValueError("local model returned an unsupported action")
    if action in {"spawn", "amend"}:
        if intent.get("role") not in roles:
            raise ValueError("local model selected an unknown role")
        if not isinstance(intent.get("task"), str) or not intent["task"].strip():
            raise ValueError("local model returned an empty task")
        if intent.get("model") not in available_models:
            raise ValueError("local model selected an unavailable model")
        if not isinstance(intent.get("model_reason"), str) or not intent["model_reason"].strip():
            raise ValueError("local model omitted its model-choice rationale")
    return intent
