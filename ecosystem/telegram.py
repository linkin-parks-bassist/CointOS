"""Minimal allowlisted Telegram command gateway using outbound polling."""
from __future__ import annotations
import json, os, threading, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from ecosystem import cli
from ecosystem.roles import list_roles
from ecosystem.presentation import humanize_notification
from ecosystem import conversation
from ecosystem.outbox import drain
from ecosystem.models import snapshot
from ecosystem.facts import lifecycle
from ecosystem.control_agent import respond as control_response

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
        if job.get("kind") == "agent-task" and job["state"] in {"queued", "ready", "running", "awaiting_verification"}:
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
    active = [job for job in jobs if job.get("kind") == "agent-task" and job.get("state") in {"queued","ready","running","awaiting_verification"}]
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


def recent_errors_text(limit: int = 5) -> str:
    now = datetime.now(timezone.utc)
    events = []
    for path in sorted((cli.ROOT / "logs/runs").glob("*.jsonl"), reverse=True)[:2]:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try: event = json.loads(line)
            except json.JSONDecodeError: continue
            if event.get("event", "").endswith(("error", "failed")) or event.get("event") == "telegram.dead_letter":
                events.append(event)
    events.sort(key=lambda item: item.get("at", ""), reverse=True)
    if not events:
        return "I checked the recent event logs; there aren't any recorded errors."
    lines = []
    for event in events[:limit]:
        instant = datetime.fromisoformat(event["at"]).astimezone()
        detail = event.get("error") or event.get("summary") or event["event"]
        lines.append(f"{instant:%-I:%M:%S %p %Z}: {detail}")
    return "yes — the most recent recorded errors are:\n" + "\n".join(lines)

def handle_natural(token: str, chat_id: int, user_id: int, command: str) -> None:
    def disaster_fallback() -> None:
        message = "the local response system has failed to answer this for five minutes. that's not normal."
        reply(token, chat_id, message)
        conversation.append(user_id, "assistant", message)
        cli.audit("telegram.disaster_fallback", user_id=user_id)
    delayed = threading.Timer(300.0, disaster_fallback)
    delayed.daemon = True
    delayed.start()
    answered = False
    try:
        history = conversation.recent(user_id)
        live = snapshot(); live["job_status"] = status_text()
        live["lifecycle_facts"] = lifecycle()
        live["recent_errors"] = recent_errors_text()
        live["available_roles"] = list_roles()
        from ecosystem.identity import active_names
        live["active_agent_names"] = sorted(active_names())
        available_models = {item["id"] for item in live["models"]}
        available_roles = set(live["available_roles"])
        def execute_tool(name: str, arguments: dict) -> dict:
            cli.audit("telegram.tool", user_id=user_id, tool=name)
            if name == "inspect_status":
                refreshed = snapshot()
                return {"ok": True, "job_status": status_text(), "models": refreshed,
                        "lifecycle_facts": lifecycle()}
            if name == "inspect_recent_errors":
                return {"ok": True, "recent_errors": recent_errors_text()}
            if name == "list_roles":
                return {"ok": True, "roles": list_roles()}
            if name in {"queue_task", "amend_pending_task"}:
                role = arguments.get("role")
                model = arguments.get("model")
                task = arguments.get("task")
                if role not in available_roles: raise ValueError("unknown role")
                if model not in available_models: raise ValueError("unavailable model")
                if not isinstance(task, str) or not task.strip(): raise ValueError("empty task")
                if name == "queue_task":
                    job_id = cli.enqueue_task(role, task, source=f"telegram:{user_id}", model=model,
                                              model_reason=arguments.get("model_reason", ""),
                                              agent_name=arguments.get("agent_name"))
                    job = json.loads((cli.ROOT / "state/jobs" / f"{job_id}.json").read_text())
                    return {"ok": True, "agent_name": job["agent_name"], "role": role,
                            "model": model, "task": task}
                job_id = cli.amend_latest_task(f"telegram:{user_id}", role, task, model,
                                               arguments.get("model_reason", ""))
                return {"ok": bool(job_id), "amended": bool(job_id), "task": task}
            if name == "pause_dispatch":
                (cli.ROOT / "state/PAUSED").touch(); cli.audit("ecosystem.paused", source="telegram", user_id=user_id)
                return {"ok": True, "paused": True}
            if name == "resume_dispatch":
                (cli.ROOT / "state/PAUSED").unlink(missing_ok=True); cli.audit("ecosystem.resumed", source="telegram", user_id=user_id)
                return {"ok": True, "paused": False}
            if name == "forget_conversation":
                conversation.forget(user_id)
                return {"ok": True, "forgotten": True}
            raise ValueError("unsupported control tool")
        response = control_response(command, history, live, execute_tool)
        if not response:
            raise ValueError("control agent returned no response")
        reply(token, chat_id, response)
        conversation.append(user_id, "user", command)
        conversation.append(user_id, "assistant", response)
        answered = True
    finally:
        if answered:
            delayed.cancel()

def handle(token: str, chat_id: int, user_id: int, command: str) -> None:
    cli.audit("telegram.command", chat_id=chat_id, user_id=user_id, command=command.split(maxsplit=1)[0])
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
                    raise
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
                    incoming = message["text"].strip()
                    try:
                        handle(token, chat, sender, incoming)
                    except Exception as error:
                        # One inbound message gets one bounded control attempt. Replaying
                        # it can duplicate actions and schedule many fallback timers.
                        cli.audit("telegram.dead_letter", user_id=sender, update_id=update["update_id"],
                                  error=f"{type(error).__name__}: {error}")
                        conversation.append(sender, "user", incoming)
                # Advance after success or deliberate dead-lettering. Network failures
                # still escape and retry because delivery outcome is then unknown.
                offset = next_offset; offset_path.write_text(str(offset))
        except Exception as error:
            cli.audit("telegram.error", error=f"{type(error).__name__}: {error}"); time.sleep(5)

if __name__ == "__main__": main()
