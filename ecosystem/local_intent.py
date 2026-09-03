"""Constrained natural-language intent routing through local Lemonade."""
from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path


ALLOWED_ACTIONS = {"spawn", "amend", "status", "roles", "pause", "chat"}
CONTROL_ROLE = Path(__file__).resolve().parents[1] / "roles/_control-plane.md"


def interpret(message: str, roles: list[str], history: list[dict[str, str]] | None = None, inventory: dict | None = None) -> dict:
    model = os.environ.get("AGENT_TELEGRAM_MODEL", "GLM-4.7-Flash-GGUF")
    inventory = inventory or {"memory_available_gb": 0, "load_average": [], "models": [{"id": model}]}
    available_models = [item["id"] for item in inventory["models"]]
    control_role = CONTROL_ROLE.read_text(encoding="utf-8")
    system = f"""{control_role}

## Live context for this turn

You route messages and schedule models for David's private local agent ecosystem.
Return exactly one JSON object and no markdown.
Schema: {{"action":"spawn|amend|status|roles|pause|chat","query":"general|last_role_spawn","query_role":"role or empty","role":"role or empty","task":"task or empty","model":"exact model ID or empty","model_reason":"brief reason or empty","agent_name":"generated name or empty","reply":"brief reply or empty"}}
Available roles: {', '.join(roles)}.
Live resource/model inventory: {json.dumps(inventory, separators=(',', ':'))}
Use spawn when David asks an agent to investigate, plan, build, fix, review, or otherwise do work.
Choose the closest available role. Preserve all important task details.
For spawn/amend choose exactly one available model. Respect an explicit user model choice.
Otherwise weigh role capability labels, model size, available memory, current load/busy state,
latency, and task difficulty. Explain the concrete tradeoff briefly in model_reason.
For spawn/amend, put a short informal acknowledgement in reply. Do not include job
IDs, JSON, queue jargon, or claim execution/completion; the work is only being handed off.
For spawn, invent an agent_name appropriate to the role or task. Usually use a
short believable human name drawn from varied world cultures rather than repeatedly
defaulting to white Anglophone names. Avoid stereotyping or exoticizing. Roughly 8%
of the time use a dry linguistic accident like “Journathan”, roughly 3% a pronounceable
alien-feeling name, and roughly 4% a task-linked pun—but only when it is actually
clever. Avoid fixed rosters, lazy puns, memes, fantasy sludge, mascot energy, or
try-hard whimsy. Respect explicit name requests and avoid active_agent_names.
Use amend when David corrects, revises, or adds to the work request he just queued.
For amend, task must be the complete corrected task, incorporating prior context—not only the changed word.
Use status only for a question actually about this machine, active work, jobs,
progress, load, schedules, or what the ecosystem is doing—not merely because a
question contains “when” or refers to prior conversation. Put a natural direct
answer using live context in reply. For "when" questions, include the exact local
date/time and timezone from lifecycle_facts when available; do not replace known
timestamps with phrases like “a while back.” You can see the machine; never claim otherwise.
For the latest spawn/instantiation of a role, set query=last_role_spawn and
query_role to the lowercase role. Use query=general for other status requests.
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
        if action == "spawn" and not isinstance(intent.get("agent_name"), str):
            raise ValueError("local model omitted the generated agent name")
    return intent

def humanize_notification(raw: str, history: list[dict[str, str]] | None = None) -> str:
    model = os.environ.get("AGENT_TELEGRAM_MODEL", "Qwen3.5-4B-GGUF")
    role = CONTROL_ROLE.read_text(encoding="utf-8")
    system = f"""{role}

Rewrite an internal agent notification as one concise Telegram message to David.
Preserve consequential facts, questions, requested decisions, failures, and useful
results. Remove job IDs, log paths, ANSI/tool chatter, JSON, and queue mechanics.
Preserve the agent's assigned name and use it naturally; names make the system fun
and help David follow who did what.
Do not invent success or details. If it is routine success, be casual (often start
with “btw,”). If it needs a response, ask naturally and clearly. Output only the message."""
    messages = [{"role":"system","content":system}, *((history or [])[-6:]), {"role":"user","content":raw}]
    body = json.dumps({"model":model,"messages":messages,"temperature":0.4,"max_tokens":600,"chat_template_kwargs":{"enable_thinking":False}}).encode()
    request = urllib.request.Request("http://127.0.0.1:13305/v1/chat/completions",data=body,headers={"Content-Type":"application/json","Authorization":"Bearer lemonade"})
    with urllib.request.urlopen(request,timeout=45) as response:
        return json.load(response)["choices"][0]["message"]["content"].strip()
