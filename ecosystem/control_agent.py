"""Deep conversational controller with narrow executable tools."""
from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path

from ecosystem.inference import request as inference_request
from ecosystem.managed_inference import request as managed_request
from ecosystem.resource_control import active_chat_model


CONTROL_ROLE = Path(__file__).resolve().parents[1] / "roles/_control-plane.md"
WORKSPACE_INSTRUCTIONS = Path.home() / "AGENTS.md"


TOOLS = [
    {"type": "function", "function": {"name": "inspect_status", "description": "Refresh exact machine, model, queue, job, and service status.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "inspect_recent_errors", "description": "Read recent durable errors and failure events with timestamps.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "list_roles", "description": "List currently available agent roles.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "queue_task", "description": "Delegate one bounded task to an agent. A role is optional advisory context; the central router chooses the actual model and treats any requested model as a hint.", "parameters": {"type": "object", "properties": {"role": {"type": ["string", "null"]}, "task": {"type": "string"}, "model": {"type": "string"}, "model_reason": {"type": "string"}, "agent_name": {"type": "string"}}, "required": ["task", "agent_name"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "amend_pending_task", "description": "Amend David's latest still-pending Telegram task when he explicitly corrects it.", "parameters": {"type": "object", "properties": {"role": {"type": ["string", "null"]}, "task": {"type": "string"}, "model": {"type": "string"}, "model_reason": {"type": "string"}}, "required": ["task", "model", "model_reason"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "pause_dispatch", "description": "Pause new agent dispatch when David asks.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "resume_dispatch", "description": "Resume agent dispatch when David asks.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "forget_conversation", "description": "Clear saved conversational history when David explicitly asks to forget it.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "publish_followup", "description": "Finish this deep turn by publishing material new information after the initial response. Use only for an actual action/dispatch, exact factual answer, consequential question or warning, correction, or result.", "parameters": {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "finish_silently", "description": "Finish this deep turn without another Telegram message because the generated initial response already handled it and no material action or fact needs reporting.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
]

TERMINAL_TOOLS = {"publish_followup", "finish_silently"}


def respond(message: str, history: list[dict[str, str]], initial_response: str | None,
            live: dict, execute: Callable[[str, dict], dict],
            infer: Callable[..., dict] | None = None,
            inference_context: dict | None = None) -> dict:
    model = active_chat_model(os.environ.get("AGENT_TELEGRAM_MODEL", "Qwen3.5-4B-GGUF"))
    initial = initial_response or "No initial response was delivered."
    system = f"""{WORKSPACE_INSTRUCTIONS.read_text(encoding='utf-8')}

{CONTROL_ROLE.read_text(encoding='utf-8')}

You are Cointelprofessional's deep control turn, running outside the Telegram
polling path. A fast model has already had the opportunity to reply. Understand
David's current message in its recent context, inspect exact facts or take narrow
tool actions where useful, then finish with exactly one terminal tool.

Use publish_followup only for material new information: an action actually taken,
a dispatched agent, an exact factual answer, a consequential question or warning,
a correction, or a result. Use finish_silently when the initial response already
handled ordinary conversation. Never send a second acknowledgement or paraphrase
of the first reply. Do not mention internal IDs unless asked. Never claim an action
unless a tool result says it occurred. Do not emit the transport-owned five-minute
failure sentence. Tool and terminal records are internal and never shown as JSON.

Current message: {message}
Initial response: {initial}
Live context at deep-turn start:
{json.dumps(live, separators=(',', ':'))}"""
    messages = [{"role": "system", "content": system}, *history[-20:],
                {"role": "user", "content": message}]
    while True:
        assistant = (infer(model=model, messages=messages, tools=TOOLS,
                           max_tokens=1400, timeout=180, temperature=0.35)
                     if infer is not None else (
                         inference_request({**inference_context, "messages": messages,
                                            "tools": TOOLS, "tool_choice": "auto", "timeout": 180,
                                            "temperature": .35}, Path(__file__).resolve().parents[1], time.monotonic)
                         if inference_context is not None else
                         managed_request(model, messages, 1400, timeout=180, tools=TOOLS,
                                         control=True)))
        calls = assistant.get("tool_calls") or []
        if not calls:
            messages.append(assistant)
            messages.append({"role": "user", "content":
                             "Finish using publish_followup or finish_silently; do not answer as bare prose."})
            continue
        messages.append(assistant)
        terminal = []
        for call in calls:
            name = call.get("function", {}).get("name", "")
            try:
                arguments = json.loads(call.get("function", {}).get("arguments") or "{}")
            except json.JSONDecodeError as error:
                arguments = {}
                result = {"ok": False, "error": f"invalid tool arguments: {error}"}
            else:
                if name in TERMINAL_TOOLS:
                    terminal.append((name, arguments))
                    result = {"ok": True, "accepted": True}
                else:
                    try:
                        result = execute(name, arguments)
                    except Exception as error:
                        result = {"ok": False, "error": f"{type(error).__name__}: {error}"}
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                             "name": name, "content": json.dumps(result, separators=(",", ":"))})
        if len(terminal) > 1:
            messages.append({"role": "user", "content": "Choose exactly one terminal tool."})
            continue
        if terminal:
            name, arguments = terminal[0]
            if name == "finish_silently":
                return {"followup": None}
            followup = arguments.get("message")
            if isinstance(followup, str) and followup.strip():
                return {"followup": followup.strip()}
            messages.append({"role": "user", "content": "publish_followup requires a non-empty message."})
