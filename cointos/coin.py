"""Coin: the user's Telegram remote control.

Every message goes straight to the work model at Coin priority. Its prompt is short and
fixed so the model starts at once; its first tool call sends a few words as proof of life,
then it looks things up and acts with the daemon's API and the kt tools, sending what it
found or did. Messages that arrive mid-turn join it. Daemon alerts are forwarded as they
appear and recorded in the conversation, so a reply to one makes sense.
"""
from __future__ import annotations

import json
import queue
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


# ---------------------------------------------------------------- turns

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
    tool("send", "Send the user a message now; the turn continues. Call it first, alone, every turn.", {"message": {"type": "string"}}, ["message"]),
    tool("done", "End this turn."),
]
PROOF_OF_LIFE = "(Coin: `send` a few words first, alone, then work.)"
# The kt tools Coin needs to read and correct knowledge; the rest stay out of its prompt.
KT_TOOLS = ("kt_lookup", "kt_find", "kt_grep", "kt_read", "kt_add", "kt_rewrite", "kt_renew")


def project_change(arguments: dict) -> dict:
    changes = {key: arguments[key] for key in ("main_branch", "priority", "enabled") if arguments.get(key) is not None}
    return call("project-set", {"project": arguments["project"], "settings": changes})


def run_agent(arguments: dict) -> dict:
    body = {key: arguments.get(key) for key in ("name", "brief", "project", "abilities", "reasoning_effort")}
    body["budget"] = {key: arguments[key] for key in ("generation_seconds", "generation_tokens") if key in arguments} or None
    return call("run-agent", body)


def output(value: str) -> dict:
    return {"ok": True, "output": value}


# What each of Coin's own tools does; `send` and `done` are handled by the turn itself.
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


def system_prompt(knowledge: dict | None) -> tuple[str, list[dict]]:
    """The fixed prompt and tools: nothing in them changes between turns, so they stay cached."""
    kt = [t for t in knowledge["tools"] if t["function"]["name"] in KT_TOOLS] if knowledge else []
    return ROLE, TOOLS + kt


def failure(error: Exception) -> str:
    """What the user is told when a turn breaks."""
    if isinstance(error, urllib.error.HTTPError):
        try:
            detail = json.load(error)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            detail = f"HTTP {error.code}"
    elif "timed out" in str(error):
        detail = "the work model didn't answer in time"
    elif isinstance(error, urllib.error.URLError):
        detail = "the daemon isn't reachable"
    else:
        detail = f"{type(error).__name__}: {error}"
    return f"I couldn't finish that ({detail}). `status` still works."


def turn(token: str, user: int, chat: int, texts: list[str], arrivals, knowledge: dict | None) -> None:
    """Work the user's message(s) with the work model until it calls `done` or runs out of rounds.
    `arrivals()` returns texts the user sent since the last round, which join the turn."""
    system, tools = system_prompt(knowledge)
    messages = [{"role": "system", "content": system}, *recent(user)]

    def hear(new: list[str]) -> None:
        for text in new:
            remember(user, "user", text)
            messages.append({"role": "user", "content": text})

    def say(text: str) -> None:
        text = text.strip()
        if text:
            remember(user, "assistant", text)
            send(token, chat, text)

    hear(texts)
    # Instructions at the top of the prompt lose to the habit of looking first; a reminder beside
    # the message wins. History keeps the user's own words.
    messages[-1] = {**messages[-1], "content": messages[-1]["content"] + "\n\n" + PROOF_OF_LIFE}
    seen: dict[str, dict] = {}
    limit = SETTINGS["max_tool_rounds"]
    for round_number in range(limit + SETTINGS["finishing_rounds"]):
        if round_number:
            hear(arrivals())
        if round_number == limit:
            messages.append({"role": "user", "content": "Out of steps: `send` what you know and call `done`."})
        assistant = complete(CONFIG["work_model"], messages, timeout=SETTINGS["model_seconds"],
                             tools=tools, temperature=0.4)
        calls = assistant.get("tool_calls") or []
        messages.append({key: value for key, value in assistant.items() if key in ("role", "content", "tool_calls")})
        if not calls:
            say(assistant.get("content") or "")
            return
        finished = False
        for request in calls:
            name = request["function"]["name"]
            try:
                arguments = json.loads(request["function"].get("arguments") or "{}")
            except ValueError as error:
                arguments, result = {}, {"ok": False, "error": f"invalid arguments: {error}"}
            else:
                if name == "send":
                    say(str(arguments.get("message", "")))
                    result = {"ok": True, "output": "sent"}
                elif name == "done":
                    finished, result = True, {"ok": True, "output": "turn ended"}
                elif round_number >= limit:
                    result = {"ok": False, "error": "out of steps: only `send` and `done` now"}
                else:
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
        if finished:
            return
    say("I ran out of steps before finishing that.")


# ---------------------------------------------------------------- service

def worker(token: str, inbox: queue.Queue) -> None:
    """One turn at a time; messages from the same user that arrive mid-turn join the running turn."""
    knowledge = kt_mcp.open_session(ROOT)
    waiting: list[tuple[int, int, str]] = []
    while True:
        if not waiting:
            waiting.append(inbox.get())
        user, chat, _ = waiting[0]
        texts = [text for who, _, text in waiting if who == user]
        waiting = [item for item in waiting if item[0] != user]

        def arrivals() -> list[str]:
            new = []
            while True:
                try:
                    item = inbox.get_nowait()
                except queue.Empty:
                    return new
                if item[0] == user:
                    new.append(item[2])
                else:
                    waiting.append(item)

        try:
            turn(token, user, chat, texts, arrivals, knowledge)
        except Exception as error:
            traceback.print_exc()
            try:
                remember(user, "assistant", failure(error))
                send(token, chat, failure(error))
            except Exception:
                traceback.print_exc()
            if knowledge and knowledge["process"].poll() is not None:
                knowledge = kt_mcp.open_session(ROOT)


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
                    remember(user, "assistant", text)
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
    inbox: queue.Queue = queue.Queue()
    threading.Thread(target=worker, args=(token, inbox), daemon=True).start()
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
            if text.strip().lower() in ("/status", "status"):
                # Mechanical, so it answers even when the work model cannot.
                try:
                    send(token, chat, status_text(timeout=CONFIG["timeouts"]["api_seconds"]))
                except Exception:
                    traceback.print_exc()
                continue
            inbox.put((user, chat, text))


def status_text(*, timeout: float | None = None) -> str:
    try:
        return cli.status_text(ledger() if timeout is None else ledger(timeout=timeout))
    except (Unreachable, ValueError) as error:
        return f"cointos status failed: {error}"


if __name__ == "__main__":
    main()
