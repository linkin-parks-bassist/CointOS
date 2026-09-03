"""Minimal allowlisted Telegram command gateway using outbound polling."""
from __future__ import annotations
import json, os, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from ecosystem import cli
from ecosystem.roles import list_roles
from ecosystem.local_intent import interpret, humanize_notification
from ecosystem import conversation
from ecosystem.outbox import drain
from ecosystem.models import snapshot

def api(token: str, method: str, values: dict) -> dict:
    data = urllib.parse.urlencode(values).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", data=data, timeout=40) as response:
        result = json.load(response)
    if not result.get("ok"): raise RuntimeError(f"Telegram {method} failed")
    return result

def reply(token: str, chat_id: int, message: str) -> None:
    api(token, "sendMessage", {"chat_id": chat_id, "text": message[:4000]})

def status_text() -> str:
    jobs = []
    counts = {}
    now = datetime.now(timezone.utc)
    for path in (cli.ROOT / "state/jobs").glob("*.json"):
        job = json.loads(path.read_text())
        counts[job["state"]] = counts.get(job["state"], 0) + 1
        if job.get("kind") == "agent-task" and job["state"] in {"queued", "ready", "running"}:
            line = f"{job['id']}: {job['state']} / {job.get('role', '?')} / {job.get('model') or 'legacy GLM default'}"
            if job["state"] == "running":
                started = datetime.fromisoformat(job["updated_at"])
                line += f" / {int((now-started).total_seconds()//60)}m elapsed"
                output = cli.ROOT / job.get("output", "")
                if output.exists():
                    idle = int((now.timestamp() - output.stat().st_mtime) // 60)
                    line += f" / output idle {idle}m"
                    if idle >= 5: line += " (possibly stalled)"
            jobs.append(line)
    active = "\n".join(jobs) if jobs else "No active agent tasks."
    return f"Paused: {(cli.ROOT / 'state/PAUSED').exists()}\nJobs: {counts}\n\nActive work:\n{active}"

def handle(token: str, chat_id: int, user_id: int, command: str) -> None:
    cli.audit("telegram.command", chat_id=chat_id, user_id=user_id, command=command.split(maxsplit=1)[0])
    if command == "/roles": reply(token, chat_id, "Roles: " + ", ".join(list_roles()))
    elif command == "/status":
        reply(token, chat_id, status_text())
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
        reply(token, chat_id, "Got it — thinking locally…")
        history = conversation.recent(user_id)
        normalized = command.lower().strip(" ?.!")
        status_phrases = ("what is the machine doing", "what's the machine doing", "whats the machine doing", "what is running", "what's running", "status", "what are you doing")
        if any(phrase in normalized for phrase in status_phrases):
            response = status_text()
            reply(token, chat_id, response)
            conversation.append(user_id, "user", command)
            conversation.append(user_id, "assistant", response)
            return
        live = snapshot()
        live["job_status"] = status_text()
        intent = interpret(command, list_roles(), history, live)
        cli.audit("telegram.intent", user_id=user_id, action=intent["action"], role=intent.get("role", ""))
        if intent["action"] == "spawn":
            job_id = cli.enqueue_task(intent["role"], intent["task"], source=f"telegram:{user_id}", model=intent["model"], model_reason=intent["model_reason"])
            response = intent.get("reply") or f"yep — I've handed that off to a {intent['role']} and I'll let you know how it goes."
            reply(token, chat_id, response)
        elif intent["action"] == "amend":
            job_id = cli.amend_latest_task(f"telegram:{user_id}", intent["role"], intent["task"], intent["model"], intent["model_reason"])
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
            def deliver(user_id: int, message: str) -> None:
                try:
                    friendly = humanize_notification(message, conversation.recent(user_id))
                except Exception as error:
                    cli.audit("telegram.humanize_failed", user_id=user_id, error=f"{type(error).__name__}: {error}")
                    friendly = message
                reply(token, user_id, friendly)
                conversation.append(user_id, "assistant", friendly)
            drain(deliver)
            updates = api(token, "getUpdates", {"offset": offset, "timeout": 30, "allowed_updates": '["message"]'})["result"]
            for update in updates:
                next_offset = update["update_id"] + 1
                message = update.get("message", {}); sender = message.get("from", {}).get("id"); chat = message.get("chat", {}).get("id")
                if sender not in allowed:
                    cli.audit("telegram.denied", user_id=sender, chat_id=chat)
                elif chat is not None and message.get("text"):
                    handle(token, chat, sender, message["text"].strip())
                # Confirm an update only after its handling completed successfully.
                offset = next_offset; offset_path.write_text(str(offset))
        except Exception as error:
            cli.audit("telegram.error", error=f"{type(error).__name__}: {error}"); time.sleep(5)

if __name__ == "__main__": main()
