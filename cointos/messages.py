"""Delivering messages between tasks into the recipient's own OpenCode session.

A message is posted once to the recipient run's session as a `noReply` user message: OpenCode
stores it, shows it in the session's TUI, and includes it in the model's very next request even
mid-turn. Successful delivery requests a reasoning-only yield at a complete generation step;
OpenCode then rereads history. Writing and tool calls are never cut short. A message waits while its
recipient has no live session (not yet started, or between runs) and is delivered on a later
tick. Caller holds LOCK for `pending`; posting happens outside it.
"""
from __future__ import annotations

import json
import secrets
import threading
import urllib.parse
import urllib.request

from cointos.state import CONFIG, LOCK, L, log
from cointos import lanes


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


def post_native(url, session, body, password, identifier):
    """Admit peer guidance without cancelling the active provider/tool or waking an idle loop."""
    from cointos import opencode2
    token = opencode2.AUTH.set(password)
    try:
        opencode2.request(url, opencode2.path(session, 'prompt'), {
            'id': identifier, 'text': body, 'resume': False, 'delivery': 'steer'},
            timeout=CONFIG['timeouts']['api_seconds'])
    finally:
        opencode2.AUTH.reset(token)


def deliver(message: dict, body: str, url: str, session: str, directory: str | None) -> None:
    with LOCK:
        task = L['tasks'].get(message['to']) or {}
        agent = L['agents'].get(task.get('agent')) or {}
        thoughts = [key for key, thought in L['thoughts'].items()
                    if thought['agent'] == task.get('agent') and agent.get('url') == url
                    and agent.get('session') == session]
    try:
        from cointos import opencode
        owner = task.get('agent')
        run = opencode.run_dir(owner) if owner else None
        metadata = json.loads((run / 'server.json').read_text()) if run and (run / 'server.json').exists() else {}
        if metadata.get('protocol') == 2:
            with LOCK:
                identifier = message.setdefault('delivery_id', 'msg_' + secrets.token_hex(16))
            post_native(url, session, body, (run / 'server-password').read_text(), identifier)
        else:
            post(url, session, directory, body)
    except (OSError, ValueError) as error:
        with LOCK:
            message.pop("posting", None)  # retried on a later tick
        log("message delivery failed", to=message["to"], error=str(error))
        return
    with LOCK:
        message.pop("posting", None)
        message["read"] = True
        lanes.interrupt_reasoning(thoughts)
    log("message delivered", sender=message["from"], to=message["to"])


def pending() -> None:
    """Start delivering every unread message whose recipient now has a live session. Caller
    holds LOCK."""
    for message in L.get("messages", []):
        if message["read"] or message.get("posting") or message["to"] == "user" or message["to"].startswith("mailbox:"):
            continue
        task = L["tasks"].get(message["to"])
        agent = L["agents"].get(task["agent"]) if task and task.get("agent") else None
        if not (agent and agent.get("url") and agent.get("session")):
            continue
        message["posting"] = True
        threading.Thread(target=deliver, args=(message, text(message), agent["url"], agent["session"], task.get("worktree")),
                         daemon=True).start()
