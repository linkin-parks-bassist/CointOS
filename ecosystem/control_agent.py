"""Deep conversational controller with narrow executable tools."""
from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path

from ecosystem import knowledge_tools
from ecosystem.inference import request as inference_request
from ecosystem.managed_inference import request as managed_request
from ecosystem.resource_control import active_chat_model


CONTROL_ROLE = Path(__file__).resolve().parents[1] / "roles/_control-plane.md"
DEEP_OUTPUT_TOKENS = 32000


TOOLS = [
    {"type": "function", "function": {"name": "inspect_status", "description": "Refresh exact machine, model, queue, job, and service status.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "inspect_task_progress", "description": "Inspect durable progress for the authenticated caller's named or latest agent task.", "parameters": {"type": "object", "properties": {"agent_name": {"type": "string"}}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "cancel_task", "description": "Cancel the authenticated caller's named or latest active agent task through durable executor cleanup.", "parameters": {"type": "object", "properties": {"agent_name": {"type": "string"}}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "inspect_recent_errors", "description": "Read recent durable errors and failure events with timestamps.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "list_roles", "description": "List currently available agent roles.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "queue_task", "description": "Delegate one concrete task to an agent. A role and model are optional hints. Choose a workspace only when the request clearly names one; otherwise the default active workspace is used.", "parameters": {"type": "object", "properties": {"role": {"type": ["string", "null"]}, "task": {"type": "string"}, "workspace": {"type": "string"}, "model": {"type": "string"}, "model_reason": {"type": "string"}, "agent_name": {"type": "string"}}, "required": ["task"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "amend_pending_task", "description": "Amend David's latest still-pending Telegram task when he explicitly corrects it.", "parameters": {"type": "object", "properties": {"role": {"type": ["string", "null"]}, "task": {"type": "string"}, "workspace": {"type": "string"}, "model": {"type": "string"}, "model_reason": {"type": "string"}}, "required": ["task"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "pause_dispatch", "description": "Pause new agent dispatch when David asks.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "resume_dispatch", "description": "Resume agent dispatch when David asks.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "forget_conversation", "description": "Clear saved conversational history when David explicitly asks to forget it.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "publish_followup", "description": "Finish this deep turn by publishing material new information after the initial response. Use only for an actual action/dispatch, exact factual answer, consequential question or warning, correction, or result.", "parameters": {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "finish_silently", "description": "Finish this deep turn without another Telegram message because the generated initial response already handled it and no material action or fact needs reporting.", "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
]

TERMINAL_TOOLS = {"publish_followup", "finish_silently"}
# A deep turn may inspect and act for this many rounds; after that only the
# terminal tools remain, so every turn ends and releases its lane.
MAXIMUM_TOOL_ROUNDS = 8
# Knowledge-root access changes are David's decision at a terminal, not Coin's.
EXCLUDED_KNOWLEDGE_TOOLS = {"kt_access_request", "kt_access_confirm", "kt_access_revoke"}


def _initial_defers_completion(response: str | None) -> bool:
    """Recognize a front reply that promises work instead of supplying the result."""
    if not isinstance(response, str):
        return False
    normalized = response.lower().replace("’", "'")
    return any(marker in normalized for marker in (
        "i'll ", "i will ", "i need to ", "let me ", "i'm checking ",
        "i'm working on ", "need to check ", "need to inspect ",
    ))


def _knowledge_guidance(knowledge) -> str:
    if knowledge is None:
        return ""
    return (
        "Knowledge trees (kt_* tools) are CointOS's maintained knowledge, including work queues. "
        "Use them to answer from checked knowledge and to record David's ideas, queue changes "
        "and corrections. A leaf is a current answer, never a log.\n"
        f"{knowledge['instructions']}\n\n"
    )


def respond(message: str, history: list[dict[str, str]], initial_response: str | None,
            live: dict, execute: Callable[[str, dict], dict],
            infer: Callable[..., dict] | None = None,
            inference_context: dict | None = None, knowledge=None) -> dict:
    model = active_chat_model(os.environ.get("AGENT_TELEGRAM_MODEL", "Qwen3.8-27B-GGUF"))
    initial_was_delivered = isinstance(initial_response, str) and bool(initial_response.strip())
    initial = initial_response.strip() if initial_was_delivered else "No initial response was delivered."
    system = f"""{CONTROL_ROLE.read_text(encoding='utf-8')}

You are Cointelprofessional's deep control turn, running outside the Telegram
polling path. A fast model has already had the opportunity to reply. Understand
David's current message in its recent context, inspect exact facts or take narrow
tool actions where useful, then finish with exactly one terminal tool.

Use publish_followup only for material new information: an action actually taken,
a dispatched agent, an exact factual answer, a consequential question or warning,
a correction, or a result. Use finish_silently when the initial response already
handled ordinary conversation. Never send a second acknowledgement or paraphrase
of the first reply. An acknowledgement or promise to check, reason, prove, inspect,
or act is not a completed answer: publish the requested result. Do not mention
internal IDs unless asked. Never claim an action
unless a tool result says it occurred. Do not emit the transport-owned five-minute
failure sentence. Tool and terminal records are internal and never shown as JSON.

{_knowledge_guidance(knowledge)}Current message: {message}
Initial response: {initial}
Live context at deep-turn start:
{json.dumps(live, separators=(',', ':'))}"""
    messages = [{"role": "system", "content": system}, *history[-20:],
                {"role": "user", "content": message}]
    tools = TOOLS + [tool for tool in (knowledge["tools"] if knowledge is not None else [])
                     if tool["function"]["name"] not in EXCLUDED_KNOWLEDGE_TOOLS]
    terminal_only = [tool for tool in TOOLS if tool["function"]["name"] in TERMINAL_TOOLS]
    successful_tool_action = False
    rounds = 0
    seen_calls: dict[str, dict] = {}
    while True:
        rounds += 1
        if rounds > MAXIMUM_TOOL_ROUNDS and tools is not terminal_only:
            tools = terminal_only
            messages.append({"role": "user", "content":
                             "Stop inspecting. Answer now with publish_followup (or finish_silently) "
                             "using what you already know."})
        assistant = (infer(model=model, messages=messages, tools=tools,
                           max_tokens=DEEP_OUTPUT_TOKENS, timeout=None, temperature=0.35)
                     if infer is not None else (
                         inference_request({**inference_context, "messages": messages,
                                            "tools": tools, "tool_choice": "auto", "timeout": None,
                                            "temperature": .35}, Path(__file__).resolve().parents[1], time.monotonic)
                         if inference_context is not None else
                         managed_request(model, messages, DEEP_OUTPUT_TOKENS, timeout=None, tools=tools,
                                         control=True)))
        calls = assistant.get("tool_calls") or []
        if not calls and rounds > MAXIMUM_TOOL_ROUNDS + 2:
            prose = (assistant.get("content") or "").strip()
            return {"followup": prose or None}
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
                elif (signature := f"{name}:{json.dumps(arguments, sort_keys=True)}") in seen_calls:
                    result = {**seen_calls[signature], "note": "You already made this exact call; "
                              "use this result instead of repeating it."}
                elif name in EXCLUDED_KNOWLEDGE_TOOLS or name not in {t["function"]["name"] for t in tools}:
                    result = {"ok": False, "error": f"{name} is not available in this turn."}
                else:
                    try:
                        result = (knowledge_tools.call(knowledge, name, arguments)
                                  if knowledge is not None and name in knowledge["names"]
                                  else execute(name, arguments))
                    except Exception as error:
                        result = {"ok": False, "error": f"{type(error).__name__}: {error}"}
                    if isinstance(result, dict):
                        seen_calls[signature] = result
                    if isinstance(result, dict) and result.get("ok") is True:
                        successful_tool_action = True
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                             "name": name, "content": json.dumps(result, separators=(",", ":"))})
        if len(terminal) > 1:
            messages.append({"role": "user", "content": "Choose exactly one terminal tool."})
            continue
        if terminal:
            name, arguments = terminal[0]
            if name == "finish_silently":
                if not initial_was_delivered:
                    messages.append({"role": "user", "content":
                                     "No initial response was delivered. Use publish_followup with a visible reply."})
                    continue
                if _initial_defers_completion(initial_response) and not successful_tool_action:
                    messages.append({"role": "user", "content":
                                     "The initial response only promised later work; it did not answer the request. "
                                     "Use publish_followup with the requested result."})
                    continue
                return {"followup": None}
            followup = arguments.get("message")
            if isinstance(followup, str) and followup.strip():
                return {"followup": followup.strip()}
            messages.append({"role": "user", "content": "publish_followup requires a non-empty message."})
