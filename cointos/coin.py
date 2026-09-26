"""Coin: David's Telegram remote control.

A fast reply from the front-desk model on its reserved lane, then, when the message
needs tools or thought, a deeper turn on the work model at Coin priority that can use
the daemon's API and the kt tools. Alerts from the daemon are forwarded as they appear.
"""
from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from cointos import cli, config as configuration, kt_mcp
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


def telegram(token: str, method: str, body: dict, timeout: float = 40) -> dict:
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
        for attempt in range(3):
            try:
                telegram(token, "sendMessage", {"chat_id": chat, "text": text[start:start + TELEGRAM_LIMIT]}, 20)
                break
            except (OSError, RuntimeError):
                if attempt == 2:
                    raise
                time.sleep(2)


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
    body = {"model": model, "messages": messages, **options}
    request = urllib.request.Request(configuration.api_url(CONFIG) + "/v1/chat/completions", json.dumps(body).encode(),
                                     {"Content-Type": "application/json", "Authorization": f"Bearer {coin_key()}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)["choices"][0]["message"]


def live_summary() -> str:
    try:
        state = cli.call()
    except (OSError, urllib.error.URLError):
        return "The CointOS daemon is not reachable right now (it may be halted or restarting)."
    agents = [f"{a['id']} ({a['project']}: {a['title']})" for a in state["agents"].values()]
    tasks = sorted(state["tasks"].values(), key=lambda t: t["updated_at"], reverse=True)[:8]
    failing = [f"{c['name']}: {c['detail']}" for c in state["checks"] if not c["ok"]]
    models = [f"{name} {'up' if m['loaded'] else 'down'}" for name, m in state["models"].items()]
    return "\n".join([
        f"Autonomous agents: {'paused' if state['paused'] else 'running'}; live agents: {', '.join(agents) or 'none'}.",
        f"Models: {', '.join(models)}. Machine: {json.dumps(state['machine'])}.",
        "Recent tasks: " + "; ".join(f"{t['project']}:{t['title']} {t['status']}" for t in tasks),
        "Self-check: " + ("green" if not failing else "failing: " + "; ".join(failing)),
        "Configured projects: " + ", ".join(p["name"] for p in CONFIG["projects"]),
    ])


def fast_reply(message: str, history: list[dict], summary: str) -> tuple[str, bool]:
    """The front desk's immediate reply, and whether a deeper turn should follow."""
    system = (f"{ROLE}\n\nYou are Coin's front desk: reply at once, briefly. Live state now:\n{summary}\n\n"
              "If the message is conversation, or the live state above answers it, answer it and set deeper "
              "to false. If it asks for an action (queuing work, drafting an idea, stopping, halting or "
              "restarting, editing knowledge) or needs careful thought or facts not shown above, set deeper to "
              "true and only acknowledge in a few words (for example \"On it.\"): a deeper turn with tools "
              "follows and does the work. You cannot act: never say that anything was done, queued, stopped, "
              "halted or started.\n"
              'Reply as JSON: {"reply": "<your message to David>", "deeper": true|false}.')
    try:
        answer = complete(CONFIG["front_model"], [{"role": "system", "content": system}, *history,
                                                  {"role": "user", "content": message}], timeout=12,
                          max_tokens=500, temperature=0.4, response_format={"type": "json_object"},
                          chat_template_kwargs={"enable_thinking": False})
    except (OSError, ValueError, KeyError, urllib.error.URLError):
        traceback.print_exc()
        return "On it; give me a moment.", True
    content = (answer.get("content") or "").strip()
    found = re.search(r"\{.*\}", content, re.DOTALL)
    try:
        parsed = json.loads(found[0]) if found else {}
    except ValueError:
        parsed = {}
    if not isinstance(parsed, dict) or not str(parsed.get("reply") or "").strip():
        return content or "On it.", True
    return str(parsed["reply"]).strip(), bool(parsed.get("deeper", True))


# ---------------------------------------------------------------- deep turn

def tool(name: str, description: str, properties: dict | None = None, required: list | None = None) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": {
        "type": "object", "properties": properties or {}, "required": required or [], "additionalProperties": False}}}


TOOLS = [
    tool("status", "Live status: models, lanes, machine, agents, tasks and self-check."),
    tool("agents", "The live agents and what each is doing."),
    tool("jobs", "Recent tasks and how they ended."),
    tool("check", "The self-check invariants."),
    tool("queue_item", "Add work to a project's queue: 'urgent' or 'queued' for concrete work, 'drafted' "
         "for an idea a manager should break down.", {
             "project": {"type": "string"}, "kind": {"type": "string", "enum": ["urgent", "queued", "drafted"]},
             "name": {"type": "string", "description": "a short name, a few words"},
             "brief": {"type": "string", "description": "the outcome wanted, where it lives, how to tell it is done"}},
         ["project", "kind", "name", "brief"]),
    tool("pause_agents", "Stop running autonomous agents (their tasks are kept) and start no new ones."),
    tool("resume_agents", "Let autonomous agents run again."),
    tool("stop_agent", "Stop one agent by id.", {"agent": {"type": "string"}}, ["agent"]),
    tool("halt", "Halt CointOS: stop the daemon and all agents and unload the models. Coin stays up."),
    tool("start", "Start CointOS again after a halt (or if it is down)."),
    tool("reply", "Finish this turn by sending David a message with new information: a result, an action "
         "taken, an answer or a warning.", {"message": {"type": "string"}}, ["message"]),
    tool("finish_silently", "Finish this turn without another message, because the first reply already covered it."),
]
TERMINAL = {"reply", "finish_silently"}


def capture(*argv) -> str:
    result = subprocess.run([str(ROOT / "bin/cointos"), *argv], capture_output=True, text=True, timeout=300)
    return (result.stdout + result.stderr).strip()


def execute(name: str, arguments: dict) -> dict:
    if name in ("status", "agents", "jobs", "check"):
        return {"ok": True, "output": capture(name)}
    if name == "queue_item":
        return {"ok": True, **cli.call("queue", arguments)}
    if name == "pause_agents":
        return cli.call("stop")
    if name == "resume_agents":
        return cli.call("go")
    if name == "stop_agent":
        return cli.call("stop-agent", arguments)
    if name == "halt":
        return {"ok": True, "output": capture("halt", "--keep-coin")}
    if name == "start":
        return {"ok": True, "output": capture("up")}
    return {"ok": False, "error": f"unknown tool {name}"}


def deep_turn(message: str, history: list[dict], first_reply: str, knowledge: dict | None) -> str | None:
    """Work the message with tools; return a follow-up message, or None to stay quiet."""
    guidance = ""
    if knowledge:
        guidance = ("\n\nKnowledge trees (kt_* tools, rooted at the CointOS repository) are CointOS's maintained "
                    "knowledge. Use them to answer from checked knowledge and to record corrections. Add work "
                    "to project queues with queue_item.\n" + knowledge["instructions"])
    system = (f"{ROLE}\n\nThis is Coin's deeper turn. The front desk already replied: {first_reply!r}. "
              "Understand David's message, look up exact facts or act with the tools, then finish with exactly "
              "one of `reply` (new information: results, actions actually taken, answers, warnings) or "
              "`finish_silently` (the first reply already covered it). Never repeat the first reply, and never "
              "claim an action a tool did not confirm." + guidance + f"\n\nLive state at the start:\n{live_summary()}")
    messages = [{"role": "system", "content": system}, *history, {"role": "user", "content": message}]
    tools = TOOLS + (knowledge["tools"] if knowledge else [])
    seen: dict[str, dict] = {}
    for round_number in range(SETTINGS["max_tool_rounds"] + 3):
        if round_number == SETTINGS["max_tool_rounds"]:
            tools = [t for t in TOOLS if t["function"]["name"] in TERMINAL]
            messages.append({"role": "user", "content": "Stop inspecting and finish now with `reply` or "
                                                        "`finish_silently`, using what you know."})
        assistant = complete(CONFIG["work_model"], messages, timeout=1800, tools=tools, temperature=0.4)
        calls = assistant.get("tool_calls") or []
        messages.append({key: value for key, value in assistant.items() if key in ("role", "content", "tool_calls")})
        if not calls:
            text = (assistant.get("content") or "").strip()
            if round_number >= SETTINGS["max_tool_rounds"]:
                return text or None
            messages.append({"role": "user", "content": "Finish with the `reply` or `finish_silently` tool."})
            continue
        for call in calls:
            name = call["function"]["name"]
            try:
                arguments = json.loads(call["function"].get("arguments") or "{}")
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
                    except SystemExit as error:  # cli.call reports API errors this way
                        result = {"ok": False, "error": str(error)}
                    except Exception as error:
                        result = {"ok": False, "error": f"{type(error).__name__}: {error}"}
                    seen[signature] = result
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "name": name,
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
    """Send David new daemon alerts (starting after the ones already seen)."""
    seen_path = COIN_STATE / "alerts-seen.json"
    last = configuration.read_json(seen_path, None)
    while True:
        try:
            alerts = cli.call()["alerts"]
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
            updates = telegram(token, "getUpdates", {"timeout": 25, "offset": offset, "allowed_updates": ["message"]})
        except Exception:
            traceback.print_exc()
            time.sleep(5)
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
            if text.strip().lower() in ("/status", "status"):
                reply, deeper = cli_text("status"), False
            else:
                reply, deeper = fast_reply(text, history, live_summary())
            if reply:
                remember(user, "assistant", reply)
                try:
                    send(token, chat, reply)
                except Exception:
                    traceback.print_exc()
            # The front desk's own judgement of "deeper" is not trusted (a small model can claim an action
            # it cannot take), so every message except a plain status request gets a deeper turn, which
            # stays silent when the first reply already covered it.
            if deeper or text.strip().lower() not in ("/status", "status"):
                turns.put((user, chat, text, history, reply))


def cli_text(command: str) -> str:
    try:
        return capture(command)
    except Exception as error:
        return f"cointos {command} failed: {error}"


if __name__ == "__main__":
    main()
