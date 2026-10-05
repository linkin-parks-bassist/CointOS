"""Delivering messages between tasks into the recipient's own OpenCode session.

A message is posted once to the recipient run's session as a `noReply` user message: OpenCode
stores it, shows it in the session's TUI, and includes it in the model's very next request even
mid-turn, so the agent sees it on its next step without a new turn. A message waits while its
recipient has no live session (not yet started, or between runs) and is delivered on a later
tick. Caller holds LOCK for `pending`; posting happens outside it.
"""
from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request

from cointos.state import CONFIG, LOCK, L, log


def text(message: dict) -> str:
    sender = L["tasks"].get(message["from"]) or {}
    who = f"{sender['name']} ({message['from']})" if sender.get("name") else message["from"]
    return f"<message from=\"{who}\">\n{message['text']}\n</message>"


def post(url: str, session: str, directory: str | None, body: str) -> None:
    query = "?" + urllib.parse.urlencode({"directory": directory}) if directory else ""
    request = urllib.request.Request(f"{url}/session/{session}/message{query}", method="POST",
                                     data=json.dumps({"noReply": True, "parts": [{"type": "text", "text": body}]}).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=CONFIG["timeouts"]["api_seconds"]):
        pass


def deliver(message: dict, body: str, url: str, session: str, directory: str | None) -> None:
    try:
        post(url, session, directory, body)
    except (OSError, ValueError) as error:
        with LOCK:
            message.pop("posting", None)  # retried on a later tick
        log("message delivery failed", to=message["to"], error=str(error))
        return
    with LOCK:
        message.pop("posting", None)
        message["read"] = True
    log("message delivered", sender=message["from"], to=message["to"])


def pending() -> None:
    """Start delivering every unread message whose recipient now has a live session. Caller
    holds LOCK."""
    for message in L.get("messages", []):
        if message["read"] or message.get("posting") or message["to"] == "user":
            continue
        task = L["tasks"].get(message["to"])
        agent = L["agents"].get(task["agent"]) if task and task.get("agent") else None
        if not (agent and agent.get("url") and agent.get("session")):
            continue
        message["posting"] = True
        threading.Thread(target=deliver, args=(message, text(message), agent["url"], agent["session"], task.get("worktree")),
                         daemon=True).start()
