"""Conversational model-driven control plane with narrow executable tools."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path


CONTROL_ROLE = Path(__file__).resolve().parents[1] / "roles/_control-plane.md"
WORKSPACE_INSTRUCTIONS = Path.home() / "AGENTS.md"
MAX_TOOL_ROUNDS = 5


TOOLS = [
    {"type": "function", "function": {"name": "inspect_status", "description": "Refresh exact machine, model, queue, job, and service status.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "inspect_recent_errors", "description": "Read recent durable errors and failure events with timestamps.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "list_roles", "description": "List currently available agent roles.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "queue_task", "description": "Delegate one bounded task to a full role-backed agent. Use this for sustained investigation, substantial reasoning, implementation, or actions that should continue after the quick initial reply. The verified result will return to David later.", "parameters": {"type": "object", "properties": {"role": {"type": "string"}, "task": {"type": "string"}, "model": {"type": "string"}, "model_reason": {"type": "string"}, "agent_name": {"type": "string"}}, "required": ["role", "task", "model", "model_reason", "agent_name"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "amend_pending_task", "description": "Amend David's latest still-pending Telegram task when he explicitly corrects that task.", "parameters": {"type": "object", "properties": {"role": {"type": "string"}, "task": {"type": "string"}, "model": {"type": "string"}, "model_reason": {"type": "string"}}, "required": ["role", "task", "model", "model_reason"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "pause_dispatch", "description": "Pause all new agent dispatch when David asks.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "resume_dispatch", "description": "Resume agent dispatch when David asks.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "forget_conversation", "description": "Clear saved conversational history when David explicitly asks to forget it.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
]


def respond(message: str, history: list[dict[str, str]], live: dict,
            execute: Callable[[str, dict], dict]) -> str:
    model = os.environ.get("AGENT_TELEGRAM_MODEL", "Qwen3.8-27B-GGUF")
    system = f"""{WORKSPACE_INSTRUCTIONS.read_text(encoding='utf-8')}

{CONTROL_ROLE.read_text(encoding='utf-8')}

You are the conversational control agent, not an intent classifier. Understand
David's message in context, decide whether any tool action is useful, use tools when
needed, observe their results, and then respond naturally. Keep this front-door turn
light and responsive. Answer immediately when the matter is conversational or can be
settled from live facts. When it requires sustained investigation, substantial
reasoning, implementation, or prolonged actions, queue one appropriately scoped
role-backed agent and give David a brief natural initial response; that agent's
verified result will be delivered later. Do not attempt the long task inside this
Telegram turn. You may call several quick tools. Do not emit JSON as prose. Do not mention internal IDs unless asked. Do not
repeat a stock acknowledgement. Ask a question only for a genuinely consequential
missing decision. If no action is needed, simply converse. Never claim an action or
fact unless present in live context or a tool result.

Live context at the start of this turn:
{json.dumps(live, separators=(',', ':'))}"""
    messages = [{"role": "system", "content": system}, *history[-20:],
                {"role": "user", "content": message}]
    for _ in range(MAX_TOOL_ROUNDS):
        body = json.dumps({"model": model, "messages": messages, "tools": TOOLS,
                           "tool_choice": "auto", "temperature": 0.35,
                           "chat_template_kwargs": {"enable_thinking": False},
                           "max_tokens": 1800}).encode()
        request = urllib.request.Request("http://127.0.0.1:13305/v1/chat/completions",
                                         data=body, headers={"Content-Type": "application/json", "Authorization": "Bearer lemonade"})
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                assistant = json.load(response)["choices"][0]["message"]
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:2000]
            raise RuntimeError(f"control model HTTP {error.code}: {detail}") from error
        tool_calls = assistant.get("tool_calls") or []
        if not tool_calls:
            content = (assistant.get("content") or "").strip()
            if content:
                return content
            continue
        messages.append(assistant)
        for call in tool_calls:
            name = call.get("function", {}).get("name", "")
            try:
                arguments = json.loads(call.get("function", {}).get("arguments") or "{}")
                result = execute(name, arguments)
            except Exception as error:
                result = {"ok": False, "error": f"{type(error).__name__}: {error}"}
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                             "name": name, "content": json.dumps(result, separators=(",", ":"))})
    raise RuntimeError("control agent exceeded its bounded tool loop")
