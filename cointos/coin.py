"""Coin: the user's Telegram remote control.

A fast reply from the front-desk model on its reserved lane, then, when the message
needs tools or thought, a deeper turn on the work model at Coin priority that can use
the daemon's API and the kt tools. Alerts from the daemon are forwarded as they appear.
"""
from __future__ import annotations

import json
import queue
import re
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

from cointos import cli, config as configuration, kt_mcp
from cointos.client import Unreachable, call, ledger
from cointos.config import KEYS, ROOT, STATE

CONFIG = configuration.load()
SETTINGS = CONFIG["coin"]
COIN_STATE = STATE / "coin"
ROLE = (ROOT / "roles/_control-plane.md").read_text(encoding="utf-8")
TELEGRAM_LIMIT = 4000


# ---------------------------------------------------------------- Telegram

def credentials() -> tuple[str, set[int]]:
    values = {}
    for line in Path(SETTINGS["telegram_env"]).expanduser().read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip().strip('"').strip("'")
    allowed = {int(part) for part in values["AGENT_TELEGRAM_ALLOWED_USER_IDS"].replace(",", " ").split()}
    return values["AGENT_TELEGRAM_BOT_TOKEN"], allowed


def telegram(token: str, method: str, body: dict, timeout: float = SETTINGS["telegram_seconds"]) -> dict:
    request = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {result.get('description')}")
    return result["result"]


def send(token: str, chat: int, text: str) -> None:
    text = text.strip() or "(nothing to say)"
    for start in range(0, len(text), TELEGRAM_LIMIT):
        for attempt in range(SETTINGS["send_attempts"]):
            try:
                telegram(token, "sendMessage", {"chat_id": chat, "text": text[start:start + TELEGRAM_LIMIT]}, 20)
                break
            except (OSError, RuntimeError):
                if attempt == SETTINGS["send_attempts"] - 1:
                    raise
                time.sleep(SETTINGS["retry_pause_seconds"])


# ---------------------------------------------------------------- memory

def history_path(user: int) -> Path:
    COIN_STATE.mkdir(parents=True, exist_ok=True)
    return COIN_STATE / f"conversation-{user}.jsonl"


def remember(user: int, role: str, content: str) -> None:
    with open(history_path(user), "a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at": time.time(), "role": role, "content": content}) + "\n")


def recent(user: int) -> list[dict]:
    try:
        lines = history_path(user).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries = [json.loads(line) for line in lines[-SETTINGS["history_messages"]:] if line.strip()]
    return [{"role": entry["role"], "content": entry["content"]} for entry in entries]


# ---------------------------------------------------------------- inference

def coin_key() -> str:
    return (configuration.read_json(KEYS, {}) or {}).get("coin", "")


def complete(model: str, messages: list[dict], timeout: float, **options) -> dict:
    """One completion through the gateway at Coin priority; the reply message."""
    body = {"model": model, "messages": messages, "reasoning_effort": CONFIG["reasoning"]["default"], **options}
    request = urllib.request.Request(configuration.api_url(CONFIG) + "/v1/chat/completions", json.dumps(body).encode(),
                                     {"Content-Type": "application/json", "Authorization": f"Bearer {coin_key()}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)["choices"][0]["message"]


def live_summary(*, timeout: float | None = None) -> str:
    try:
        state = ledger() if timeout is None else ledger(timeout=timeout)
    except (Unreachable, ValueError):
        return "The CointOS daemon is not reachable right now (it may be halted or restarting)."
    agents = [f"{a['id']} {a['state']} on {a['place']}: {a['title']}" for a in state["agents"].values()]
    tasks = sorted(state["tasks"].values(), key=lambda t: t["updated_at"], reverse=True)[:8]
    failing = [f"{c['name']}: {c['detail']}" for c in state["checks"] if not c["ok"]]
    models = [f"{name} {'up' if m['up'] else 'down'}" for name, m in state["models"].items()]
    memory = state["memory"]
    return "\n".join([
        f"Autonomous agents: {'paused' if state['paused'] else 'running'}; live agents: {'; '.join(agents) or 'none'}.",
        f"Models: {', '.join(models)}. Memory headroom: {memory.get('headroom_gb')} GB.",
        "Recent tasks: " + "; ".join(f"{t['place']}:{t['title']} {t['status']}" for t in tasks),
        "Self-check: " + ("green" if not failing else "failing: " + "; ".join(failing)),
        "Configured projects: " + ", ".join(p["name"] for p in state.get("projects", CONFIG["projects"])),
    ])


def trim_fast_reply(text: str) -> str:
    """Drop a final question from a multi-sentence front-desk reply."""
    text = text.strip()
    if text.endswith("?"):
        boundaries = list(re.finditer(r"[.!?]\s+", text))
        if boundaries:
            text = text[:boundaries[-1].start() + 1]
    return text


def fast_reply(message: str, history: list[dict], summary: str, *, deadline: float | None = None) -> str:
    """The front desk's immediate, brief reply. It cannot act: a deeper turn with tools follows
    every message except a plain status request, and stays silent if this reply covered it."""
    system = (f"{ROLE}\n\nYou are Coin's front desk: reply at once, briefly. Live state now:\n{summary}\n\n"
              "If the message is conversation, or the live state above answers it, answer it. If it asks for an "
              "action (queuing work, drafting an idea, stopping, halting or restarting, editing knowledge) or needs "
              "careful thought or facts not shown above, only acknowledge in a few words (for example \"On it.\"): "
              "a deeper turn with tools follows and does the work. You cannot act: never say that anything was done, "
              "queued, stopped, halted or started.")
    timeout = SETTINGS["reply_seconds"]
    if deadline is not None:
        timeout = min(timeout, deadline - time.monotonic())
    if timeout <= 0:
        return "On it; give me a moment."
    try:
        answer = complete(CONFIG["front_model"], [{"role": "system", "content": system}, *history,
                                                  {"role": "user", "content": message}], timeout=timeout,
                          max_tokens=SETTINGS["reply_tokens"], temperature=0.4,
                          chat_template_kwargs={"enable_thinking": False})
    except (OSError, ValueError, KeyError, urllib.error.URLError):
        traceback.print_exc()
        return "On it; give me a moment."
    return trim_fast_reply(answer.get("content") or "") or "On it."


def first_reply(message: str, history: list[dict]) -> str:
    """Share the front-desk preparation budget between control lookup and inference."""
    deadline = time.monotonic() + SETTINGS["reply_seconds"]
    timeout = min(CONFIG["timeouts"]["api_seconds"], SETTINGS["reply_seconds"])
    if message.strip().lower() in ("status", "/status"):
        return status_text(timeout=timeout)
    summary = live_summary(timeout=timeout)
    return fast_reply(message, history, summary, deadline=deadline)


# ---------------------------------------------------------------- deep turn

def tool(name: str, description: str, properties: dict | None = None, required: list | None = None) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties or {}, "required": required or [], "additionalProperties": False}}}


TOOLS = [
    tool("status", "Live status: models, lanes, machine, agents, tasks and self-check."),
    tool("agents", "The live agents and what each is doing."),
    tool("jobs", "Recent tasks and how they ended."),
    tool("check", "The self-check invariants."),
    tool("queue_item", "Add work to a project's queue: 'urgent' or 'queued' for concrete work, 'command' "
         "for any bounded managerial action or planning request.", {
             "project": {"type": "string"}, "kind": {"type": "string", "enum": ["urgent", "queued", "command"]},
             "name": {"type": "string", "description": "a short name, a few words"},
             "brief": {"type": "string", "description": "the outcome wanted, where it lives, how to tell it is done"}},
         ["project", "kind", "name", "brief"]),
    tool("hold_item", "Keep a queue item (PROJECT:ITEM) from starting while the user decides; release=true lifts the hold.", {
             "item": {"type": "string"}, "release": {"type": "boolean"}}, ["item"]),
    tool("revise_item", "Change a queue item's brief while retaining its stage, reasoning and budget; its task restarts on the new brief.", {
             "item": {"type": "string"}, "brief": {"type": "string", "description": "the complete revised brief"},
             "reason": {"type": "string"}}, ["item", "brief", "reason"]),
    tool("projects", "List projects registered with CointOS, including priority and enabled state."),
    tool("project_add", "Register an existing Git repository with CointOS.", {
             "path": {"type": "string"}, "name": {"type": "string"},
             "main_branch": {"type": "string"}, "priority": {"type": "integer"},
             "enabled": {"type": "boolean"}}, ["path"]),
    tool("project_new", "Create a folder and Git repository, initialize its project knowledge tree, commit it, and register it with CointOS.", {
             "name": {"type": "string"}, "path": {"type": "string"},
             "main_branch": {"type": "string"}, "priority": {"type": "integer"},
             "enabled": {"type": "boolean"}}, ["name"]),
    tool("project_set", "Change a registered project's priority, enabled state or main branch.", {
             "project": {"type": "string"}, "main_branch": {"type": "string"},
             "priority": {"type": "integer"}, "enabled": {"type": "boolean"}}, ["project"]),
    tool("project_remove", "Remove an idle project from CointOS without deleting its repository.", {
             "project": {"type": "string"}}, ["project"]),
    tool("run_agent", "Start one ad-hoc operator with explicit system/project scope, abilities, reasoning and budget.", {
             "name": {"type": "string"}, "brief": {"type": "string"}, "project": {"type": "string"},
             "abilities": {"type": "array", "items": {"type": "string", "enum": ["standard", "control", "network"]}},
             "reasoning_effort": {"type": "string", "enum": ["low", "medium", "xhigh"]},
             "generation_seconds": {"type": "number"}, "generation_tokens": {"type": "integer"}},
         ["name", "brief"]),
    tool("scout", "Schedule the canonical system-wide loose-end scout now."),
    tool("pause_agents", "Stop running autonomous agents (their tasks are kept) and start no new ones."),
    tool("resume_agents", "Let autonomous agents run again."),
    tool("kill_agent", "Kill one run by agent id; preserve artifacts and hold unfinished work until explicitly resumed.",
         {"agent": {"type": "string"}}, ["agent"]),
    tool("resume_task", "Release a killed task for scheduling.", {"task": {"type": "string"}}, ["task"]),
    tool("halt", "Halt CointOS: stop the daemon and all agents and unload the models. Coin stays up."),
    tool("start", "Start CointOS again after a halt (or if it is down)."),
    tool("restart", "Drain replies and restart only the daemon, preserving agents, sessions and loaded models."),
    tool("reply", "Finish this turn by sending the user a message with new information: a result, an action "
         "taken, an answer or a warning.", {"message": {"type": "string"}}, ["message"]),
    tool("finish_silently", "Finish this turn without another message, because the first reply already covered it."),
]
TERMINAL = {"reply", "finish_silently"}


def project_change(arguments: dict) -> dict:
    changes = {key: arguments[key] for key in ("main_branch", "priority", "enabled") if arguments.get(key) is not None}
    return call("project-set", {"project": arguments["project"], "settings": changes})


def run_agent(arguments: dict) -> dict:
    body = {key: arguments.get(key) for key in ("name", "brief", "project", "abilities", "reasoning_effort")}
    body["budget"] = {key: arguments[key] for key in ("generation_seconds", "generation_tokens") if key in arguments} or None
    return call("run-agent", body)


def output(value: str) -> dict:
    return {"ok": True, "output": value}


# What each of Coin's own tools does; `reply` and `finish_silently` end the turn instead.
EXECUTE = {
    "status": lambda arguments: output(cli.status_text(ledger())),
    "agents": lambda arguments: output(cli.agents_text(ledger())),
    "jobs": lambda arguments: output(cli.jobs_text(ledger())),
    "check": lambda arguments: output(cli.checks_text(ledger())[0]),
    "queue_item": lambda arguments: call("queue", arguments),
    "hold_item": lambda arguments: call("unhold" if arguments.get("release") else "hold", {"item": arguments["item"]}),
    "revise_item": lambda arguments: call("revise", arguments),
    "projects": lambda arguments: output(cli.projects_text(call("project-list")["projects"])),
    "project_add": lambda arguments: call("project-add", arguments),
    "project_new": lambda arguments: call("project-new", arguments),
    "project_set": project_change,
    "project_remove": lambda arguments: call("project-remove", arguments),
    "run_agent": run_agent,
    "scout": lambda arguments: call("scout"),
    "pause_agents": lambda arguments: call("stop"),
    "resume_agents": lambda arguments: call("go"),
    "kill_agent": lambda arguments: call("kill-agent", arguments),
    "resume_task": lambda arguments: call("resume-task", arguments),
    "halt": lambda arguments: output(cli.halt(keep_coin=True)),
    "start": lambda arguments: output(cli.up()),
    "restart": lambda arguments: output(cli.restart()),
}


def execute(name: str, arguments: dict) -> dict:
    if name not in EXECUTE:
        return {"ok": False, "error": f"unknown tool {name}"}
    try:
        return EXECUTE[name](arguments)
    except SystemExit as error:
        # CLI control refusals are tool results, not a reason to kill Coin's worker.
        return {"ok": False, "error": str(error)}


def deep_turn(message: str, history: list[dict], first_reply: str, knowledge: dict | None) -> str | None:
    """Work the message with tools; return a follow-up message, or None to stay quiet."""
    guidance = ""
    if knowledge:
        guidance = ("\n\nKnowledge trees (kt_* tools, rooted at the CointOS repository) are CointOS's maintained "
                    "knowledge. Use them to answer from checked knowledge and to record corrections. Add work "
                    "to project queues with queue_item.\n" + knowledge["instructions"])
    system = (f"{ROLE}\n\nThis is Coin's deeper turn. The front desk already replied: {first_reply!r}. "
              "Understand the user's message, look up exact facts or act with the tools, then finish with exactly "
              "one of `reply` (new information: results, actions actually taken, answers, warnings) or "
              "`finish_silently` (the first reply already covered it). Never repeat the first reply, and never "
              "claim an action a tool did not confirm." + guidance + f"\n\nLive state at the start:\n{live_summary()}")
    messages = [{"role": "system", "content": system}, *history, {"role": "user", "content": message}]
    tools = TOOLS + (knowledge["tools"] if knowledge else [])
    seen: dict[str, dict] = {}
    for round_number in range(SETTINGS["max_tool_rounds"] + SETTINGS["finishing_rounds"]):
        if round_number == SETTINGS["max_tool_rounds"]:
            tools = [t for t in TOOLS if t["function"]["name"] in TERMINAL]
            messages.append({"role": "user", "content": "Stop inspecting and finish now with `reply` or "
                                                        "`finish_silently`, using what you know."})
        assistant = complete(CONFIG["work_model"], messages, timeout=SETTINGS["deep_turn_seconds"], tools=tools, temperature=0.4)
        calls = assistant.get("tool_calls") or []
        messages.append({key: value for key, value in assistant.items() if key in ("role", "content", "tool_calls")})
        if not calls:
            text = (assistant.get("content") or "").strip()
            if round_number >= SETTINGS["max_tool_rounds"]:
                return text or None
            messages.append({"role": "user", "content": "Finish with the `reply` or `finish_silently` tool."})
            continue
        for request in calls:
            name = request["function"]["name"]
            try:
                arguments = json.loads(request["function"].get("arguments") or "{}")
            except ValueError as error:
                arguments, result = {}, {"ok": False, "error": f"invalid arguments: {error}"}
            else:
                if name == "reply":
                    return str(arguments.get("message", "")).strip() or None
                if name == "finish_silently":
                    return None
                signature = name + json.dumps(arguments, sort_keys=True)
                if signature in seen:
                    result = {**seen[signature], "note": "You already made this call; use this result."}
                else:
                    try:
                        result = (kt_mcp.call(knowledge, name, arguments) if knowledge and name in knowledge["names"]
                                  else execute(name, arguments))
                    except Exception as error:  # a refusal or failure is a result the turn can use
                        result = {"ok": False, "error": f"{type(error).__name__}: {error}"}
                    seen[signature] = result
            messages.append({"role": "tool", "tool_call_id": request.get("id", ""), "name": name,
                             "content": json.dumps(result)[:20000]})
    return None


# ---------------------------------------------------------------- service

def deep_worker(token: str, turns: queue.Queue) -> None:
    knowledge = kt_mcp.open_session(ROOT)
    while True:
        user, chat, message, history, first = turns.get()
        try:
            followup = deep_turn(message, history, first, knowledge)
        except Exception as error:
            traceback.print_exc()
            followup = f"I couldn't finish working on that: {type(error).__name__}: {error}"
            if knowledge and knowledge["process"].poll() is not None:
                knowledge = kt_mcp.open_session(ROOT)
        if followup:
            remember(user, "assistant", followup)
            try:
                send(token, chat, followup)
            except Exception:
                traceback.print_exc()


def alert_forwarder(token: str, allowed: set[int]) -> None:
    """Send the user new daemon alerts (starting after the ones already seen)."""
    seen_path = COIN_STATE / "alerts-seen.json"
    last = configuration.read_json(seen_path, None)
    while True:
        try:
            alerts = ledger()["alerts"]
            if last is None:
                last = max((a["id"] for a in alerts), default=0)
            fresh = [a for a in alerts if a["id"] > last]
            if fresh:
                text = "\n".join("⚠️ " + a["text"] for a in fresh)
                for user in allowed:
                    send(token, user, text)
                last = fresh[-1]["id"]
                configuration.write_json(seen_path, last)
        except Exception:
            pass
        time.sleep(SETTINGS["alert_poll_seconds"])


def main() -> None:
    token, allowed = credentials()
    COIN_STATE.mkdir(parents=True, exist_ok=True)
    offset_path = COIN_STATE / "telegram-offset.json"
    offset = configuration.read_json(offset_path, None)
    turns: queue.Queue = queue.Queue()
    threading.Thread(target=deep_worker, args=(token, turns), daemon=True).start()
    threading.Thread(target=alert_forwarder, args=(token, allowed), daemon=True).start()
    while True:
        try:
            updates = telegram(token, "getUpdates", {"timeout": SETTINGS["long_poll_seconds"], "offset": offset, "allowed_updates": ["message"]})
        except Exception:
            traceback.print_exc()
            time.sleep(SETTINGS["error_pause_seconds"])
            continue
        for update in updates:
            offset = update["update_id"] + 1
            configuration.write_json(offset_path, offset)
            message = update.get("message") or {}
            user, chat, text = (message.get("from") or {}).get("id"), (message.get("chat") or {}).get("id"), message.get("text")
            if user not in allowed or not text:
                continue
            history = recent(user)
            remember(user, "user", text)
            status_request = text.strip().lower() in ("/status", "status")
            reply = first_reply(text, history)
            remember(user, "assistant", reply)
            try:
                send(token, chat, reply)
            except Exception:
                traceback.print_exc()
            if not status_request:
                turns.put((user, chat, text, history, reply))


def status_text(*, timeout: float | None = None) -> str:
    try:
        return cli.status_text(ledger() if timeout is None else ledger(timeout=timeout))
    except (Unreachable, ValueError) as error:
        return f"cointos status failed: {error}"


if __name__ == "__main__":
    main()
