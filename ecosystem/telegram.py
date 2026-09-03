"""Minimal allowlisted Telegram command gateway using outbound polling."""
from __future__ import annotations
import json, os, threading, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from ecosystem import cli
from ecosystem.roles import list_roles
from ecosystem.local_intent import interpret, humanize_notification
from ecosystem import conversation
from ecosystem.outbox import drain
from ecosystem.models import snapshot
from ecosystem.facts import lifecycle
from ecosystem.queries import answer as answer_query, resolve as resolve_query

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

def friendly_status() -> str:
    jobs = [json.loads(path.read_text()) for path in (cli.ROOT / "state/jobs").glob("*.json")]
    active = [job for job in jobs if job.get("kind") == "agent-task" and job.get("state") in {"queued","ready","running"}]
    if active:
        descriptions = []
        for job in active:
            name = job.get("agent_name") or "an older unnamed agent"
            descriptions.append(f"{name} is {job['state']} on {job.get('task','something')[:120]}")
        opening = "; ".join(descriptions) + "."
    else:
        opening = "nothing's running right now — the machine's ready for whatever's next."
    completed = sum(job.get("kind") == "agent-task" and job.get("state") == "completed" for job in jobs)
    failed = sum(job.get("kind") == "agent-task" and job.get("state") == "failed" for job in jobs)
    history = f" {completed} agent jobs have finished"
    if failed: history += f", and {failed} older attempts failed"
    return opening + history + "."

def natural_reply(value: object, fallback: str) -> str:
    text = value.strip() if isinstance(value, str) else ""
    if not text or text.startswith(("{", "[")):
        return fallback
    return text

def handle_natural(token: str, chat_id: int, user_id: int, command: str) -> None:
    delayed = threading.Timer(15.0, reply, args=(token, chat_id, "this one's taking longer than usual — still on it."))
    delayed.daemon = True
    delayed.start()
    try:
        history = conversation.recent(user_id)
        normalized = command.lower().strip(" ?.!")
        status_phrases = ("what is the machine doing", "what's the machine doing", "whats the machine doing", "what is running", "what's running", "status", "what are you doing")
        if any(phrase in normalized for phrase in status_phrases):
            response = friendly_status()
            reply(token, chat_id, response)
            conversation.append(user_id, "user", command)
            conversation.append(user_id, "assistant", response)
            return
        live = snapshot(); live["job_status"] = status_text()
        live["lifecycle_facts"] = lifecycle()
        from ecosystem.identity import active_names
        live["active_agent_names"] = sorted(active_names())
        intent = interpret(command, list_roles(), history, live)
        cli.audit("telegram.intent", user_id=user_id, action=intent["action"], role=intent.get("role", ""))
        if intent["action"] == "spawn":
            job_id = cli.enqueue_task(intent["role"], intent["task"], source=f"telegram:{user_id}", model=intent["model"], model_reason=intent["model_reason"], agent_name=intent["agent_name"])
            job = json.loads((cli.ROOT / "state/jobs" / f"{job_id}.json").read_text())
            response = f"yep — {job['agent_name']}'s on it. I'll let you know how they go."
            reply(token, chat_id, response)
        elif intent["action"] == "amend":
            job_id = cli.amend_latest_task(f"telegram:{user_id}", intent["role"], intent["task"], intent["model"], intent["model_reason"])
            response = (f"yep, fixed that up — the task now says: {intent['task']}" if job_id else
                        "that one's already started or finished, so I haven't silently changed it. want me to queue a corrected follow-up?")
            reply(token, chat_id, response)
        elif intent["action"] == "status":
            query, query_role = resolve_query(command, intent.get("query", "general"), intent.get("query_role", ""))
            exact = answer_query(query, query_role, live["lifecycle_facts"])
            response = exact or natural_reply(intent.get("reply"), friendly_status())
            reply(token, chat_id, response)
        elif intent["action"] == "roles":
            response = natural_reply(intent.get("reply"), "I've currently got intake, worker, and steward roles.")
            reply(token, chat_id, response)
        elif intent["action"] == "pause":
            (cli.ROOT / "state/PAUSED").touch(); cli.audit("ecosystem.paused", source="telegram", user_id=user_id)
            response = natural_reply(intent.get("reply"), "yep, paused. nothing new will start until you resume it.")
            reply(token, chat_id, response)
        else:
            response = natural_reply(intent.get("reply"), "what would you like an agent to do?")
            reply(token, chat_id, response)
        conversation.append(user_id, "user", command)
        conversation.append(user_id, "assistant", response)
    finally:
        delayed.cancel()

def handle(token: str, chat_id: int, user_id: int, command: str) -> None:
    cli.audit("telegram.command", chat_id=chat_id, user_id=user_id, command=command.split(maxsplit=1)[0])
    if command == "/roles": reply(token, chat_id, "Roles: " + ", ".join(list_roles()))
    elif command == "/status":
        reply(token, chat_id, friendly_status())
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
        job = json.loads((cli.ROOT / "state/jobs" / f"{job_id}.json").read_text())
        reply(token, chat_id, f"yep — {job['agent_name']}'s on it. I'll let you know how they go.")
    elif command.startswith("/"):
        reply(token, chat_id, "Commands: /spawn ROLE TASK, /roles, /status, /pause, /forget — or just speak normally.")
    else:
        handle_natural(token, chat_id, user_id, command)

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
