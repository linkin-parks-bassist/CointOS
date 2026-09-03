"""Minimal allowlisted Telegram command gateway using outbound polling."""
from __future__ import annotations
import json, os, time, urllib.parse, urllib.request
from ecosystem import cli
from ecosystem.roles import list_roles
from ecosystem.local_intent import interpret
from ecosystem import conversation
from ecosystem.outbox import drain

def api(token: str, method: str, values: dict) -> dict:
    data = urllib.parse.urlencode(values).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", data=data, timeout=40) as response:
        result = json.load(response)
    if not result.get("ok"): raise RuntimeError(f"Telegram {method} failed")
    return result

def reply(token: str, chat_id: int, message: str) -> None:
    api(token, "sendMessage", {"chat_id": chat_id, "text": message[:4000]})

def handle(token: str, chat_id: int, user_id: int, command: str) -> None:
    cli.audit("telegram.command", chat_id=chat_id, user_id=user_id, command=command.split(maxsplit=1)[0])
    if command == "/roles": reply(token, chat_id, "Roles: " + ", ".join(list_roles()))
    elif command == "/status":
        counts = {}
        for path in (cli.ROOT / "state/jobs").glob("*.json"):
            state = json.loads(path.read_text())["state"]; counts[state] = counts.get(state, 0) + 1
        reply(token, chat_id, f"Paused: {(cli.ROOT / 'state/PAUSED').exists()}\nJobs: {counts}")
    elif command == "/pause":
        (cli.ROOT / "state/PAUSED").touch(); cli.audit("ecosystem.paused", source="telegram", user_id=user_id)
        reply(token, chat_id, "Paused. No checker will prepare or launch work.")
    elif command == "/forget":
        conversation.forget(user_id)
        reply(token, chat_id, "Forgot our saved conversational context. Jobs and audit records were not deleted.")
    elif command.startswith("/spawn "):
        parts = command.split(maxsplit=2)
        if len(parts) < 3: reply(token, chat_id, "Usage: /spawn ROLE TASK"); return
        job_id = cli.enqueue_task(parts[1], parts[2], source=f"telegram:{user_id}")
        reply(token, chat_id, f"Queued {job_id} with role {parts[1]}. The local executor will pick it up shortly.")
    elif command.startswith("/"):
        reply(token, chat_id, "Commands: /spawn ROLE TASK, /roles, /status, /pause, /forget — or just speak normally.")
    else:
        history = conversation.recent(user_id)
        intent = interpret(command, list_roles(), history)
        cli.audit("telegram.intent", user_id=user_id, action=intent["action"], role=intent.get("role", ""))
        if intent["action"] == "spawn":
            job_id = cli.enqueue_task(intent["role"], intent["task"], source=f"telegram:{user_id}")
            response = f"Got it — queued {job_id} as {intent['role']}. The local executor will pick it up shortly.\n\nTask: {intent['task']}"
            reply(token, chat_id, response)
        elif intent["action"] == "amend":
            job_id = cli.amend_latest_task(f"telegram:{user_id}", intent["role"], intent["task"])
            if job_id:
                response = f"Corrected {job_id}.\n\nUpdated task: {intent['task']}"
            else:
                response = "That job has already started or finished, so I didn't silently change it. Tell me whether to queue a corrected follow-up."
            reply(token, chat_id, response)
        elif intent["action"] == "status": handle(token, chat_id, user_id, "/status")
        elif intent["action"] == "roles": handle(token, chat_id, user_id, "/roles")
        elif intent["action"] == "pause": handle(token, chat_id, user_id, "/pause")
        else:
            response = intent.get("reply") or "Tell me what you'd like an agent to do."
            reply(token, chat_id, response)
        if intent["action"] in {"spawn", "amend", "chat"}:
            conversation.append(user_id, "user", command)
            conversation.append(user_id, "assistant", response)

def main() -> None:
    token = os.environ.get("AGENT_TELEGRAM_BOT_TOKEN")
    allowed = {int(v) for v in os.environ.get("AGENT_TELEGRAM_ALLOWED_USER_IDS", "").split(",") if v.strip()}
    if not token or not allowed: raise SystemExit("set AGENT_TELEGRAM_BOT_TOKEN and AGENT_TELEGRAM_ALLOWED_USER_IDS")
    cli.initialize(); offset_path = cli.ROOT / "state/telegram-offset"
    offset = int(offset_path.read_text()) if offset_path.exists() else 0
    while True:
        try:
            drain(lambda user_id, text: reply(token, user_id, text))
            updates = api(token, "getUpdates", {"offset": offset, "timeout": 30, "allowed_updates": '["message"]'})["result"]
            for update in updates:
                offset = update["update_id"] + 1; offset_path.write_text(str(offset))
                message = update.get("message", {}); sender = message.get("from", {}).get("id"); chat = message.get("chat", {}).get("id")
                if sender not in allowed: cli.audit("telegram.denied", user_id=sender, chat_id=chat); continue
                if chat is not None and message.get("text"): handle(token, chat, sender, message["text"].strip())
        except Exception as error:
            cli.audit("telegram.error", error=f"{type(error).__name__}: {error}"); time.sleep(5)

if __name__ == "__main__": main()
