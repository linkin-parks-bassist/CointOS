"""Human-facing views of CointOS: who is alive, what ran, and overall health.

Data functions return plain records; render functions turn them into terminal text.
A future web view should reuse the data functions, not the renderers.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from ecosystem import cli

ACTIVE = ("running", "runner_starting", "claimed", "ready", "queued", "awaiting_verification")
UNITS = ("agent-telegram", "agent-control-worker", "agent-inference-proxy", "agent-resource-guard",
         "agent-notifier", "agent-spawner.timer", "agent-watchdog.timer",
         "agent-backend-profile.timer", "agent-ecosystem.path")
STATE_COLOUR = {"running": "green", "runner_starting": "green", "claimed": "cyan", "ready": "cyan",
                "queued": "yellow", "awaiting_verification": "cyan", "completed": "green",
                "failed": "red", "rejected": "red", "cancelled": "grey", "interrupted": "red",
                "reconciliation_required": "red"}
CODES = {"green": "32", "red": "31", "yellow": "33", "cyan": "36", "grey": "90", "bold": "1",
         "dim": "2", "magenta": "35"}


# ── data ────────────────────────────────────────────────────────────────────

def _jobs() -> list[dict]:
    jobs = []
    for path in (cli.ROOT / "state/jobs").glob("task-*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if job.get("kind") == "agent-task":
            jobs.append(job)
    return jobs


def _when(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _origin(source: str) -> tuple[str, str | None]:
    """Who asked for a job, and the queue item it serves if any."""
    if source.startswith("spawner:"):
        _, kind, target = (source.split(":", 2) + ["", ""])[:3]
        return f"auto·{kind}", target if target.endswith(".md") else None
    for prefix, label in (("telegram:", "you·Coin"), ("verification:", "review"),
                          ("watchdog", "watchdog"), ("local-cli", "you"), ("resource", "survivor")):
        if source.startswith(prefix):
            return label, None
    return source.split(":", 1)[0] or "?", None


def _activity(job: dict) -> dict:
    """Tool calls and last output time from the worker's OpenCode log."""
    output = job.get("output")
    path = cli.ROOT / output if isinstance(output, str) and output else None
    if path is None or not path.is_file():
        return {"tool_calls": 0, "last_activity": None}
    text = path.read_text(encoding="utf-8", errors="replace")
    return {"tool_calls": text.count('"type":"tool_use"'),
            "last_activity": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)}


def _summary(job: dict, item: str | None) -> str:
    if item:
        leaf = Path(item)
        return f"{leaf.parent.name}/{leaf.stem}"
    if job.get("source", "").startswith("spawner:survey"):
        return "survey the project and queue next steps"
    task = job.get("task") or ""
    card = re.search(r"Maintenance check `([^`]+)`", task)
    if card:
        return f"maintenance: {card.group(1)}"
    first = next((line.strip() for line in task.splitlines() if line.strip()), "")
    return first


def agent_record(job: dict, now: datetime) -> dict:
    origin, item = _origin(job.get("source", ""))
    workspace = (job.get("task_contract") or {}).get("scope", {}).get("workspace", "")
    created = _when(job.get("created_at"))
    updated = _when(job.get("updated_at"))
    end = now if job.get("state") in ACTIVE else (updated or now)
    return {
        "id": job.get("id"), "name": job.get("agent_name") or job.get("id"),
        "role": job.get("role") or "—", "state": job.get("state"), "model": job.get("model"),
        "origin": origin, "item": item, "workspace": Path(workspace).name if workspace else "",
        "what": _summary(job, item), "created_at": created, "updated_at": updated,
        "age_seconds": (end - created).total_seconds() if created else None,
        "outcome": job.get("failure_reason") or job.get("cancellation_reason") or job.get("model_reason")
        if job.get("state") not in ACTIVE or job.get("state") == "queued" else None,
        **_activity(job),
    }


def agents(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    rows = [agent_record(job, now) for job in _jobs() if job.get("state") in ACTIVE]
    return sorted(rows, key=lambda row: (ACTIVE.index(row["state"]), row["created_at"] or now))


def recent_jobs(limit: int = 20, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    jobs = sorted(_jobs(), key=lambda job: job.get("updated_at", ""), reverse=True)[:limit]
    return [agent_record(job, now) for job in jobs]


def _lanes(args: object) -> int | None:
    match = re.search(r"--parallel\s+(\d+)", args if isinstance(args, str) else "")
    return int(match.group(1)) if match else None


def health() -> dict:
    def read(name: str) -> dict:
        try:
            return json.loads((cli.ROOT / "state" / name).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    control, workload = read("resource-control.json"), read("workload-control.json")
    models, backend_error = [], None
    try:
        from ecosystem.resource_control import lemonade_health
        reply = lemonade_health()
        for item in reply.get("all_models_loaded") or []:
            if isinstance(item, dict) and item.get("loaded"):
                options = item.get("recipe_options") or {}
                models.append({"model": item.get("model_name"), "status": item.get("status"),
                               "pinned": bool(item.get("pinned")),
                               "busy": bool(item.get("is_busy")),
                               "lanes": _lanes(options.get("llamacpp_args")),
                               "context_tokens": options.get("ctx_size")})
    except Exception as error:
        backend_error = f"{type(error).__name__}: {error}"
    return {"resource_mode": control.get("mode"), "incident": control.get("incident_id"),
            "work_gate": workload.get("mode"), "paused": (cli.ROOT / "state/PAUSED").exists(),
            "models": models, "backend_error": backend_error}


def services() -> list[dict]:
    names = [unit if "." in unit else unit + ".service" for unit in UNITS]
    done = subprocess.run(["systemctl", "--user", "is-active", *names],
                          capture_output=True, text=True)
    states = done.stdout.split()
    return [{"unit": name, "state": states[index] if index < len(states) else "unknown"}
            for index, name in enumerate(names)]


def queues() -> list[dict]:
    try:
        config = json.loads((cli.ROOT / "config/spawner.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    from ecosystem.spawner import _status
    rows = []
    for project in (Path(p).expanduser() for p in config.get("projects", [])):
        counts: dict[str, dict[str, int]] = {}
        for branch in ("urgent", "queued", "drafted"):
            folder = project / ".knowledge/what/is" / branch
            for leaf in folder.rglob("*.md") if folder.is_dir() else ():
                status = _status(leaf) or "no status"
                counts.setdefault(branch, {}).setdefault(status, 0)
                counts[branch][status] += 1
        rows.append({"project": project.name, "counts": counts})
    return rows


def spawner_state() -> dict:
    try:
        config = json.loads((cli.ROOT / "config/spawner.json").read_text(encoding="utf-8"))
        state = json.loads((cli.ROOT / "state/spawner.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        config, state = locals().get("config", {}), {}
    return {"enabled": config.get("enabled", False), "max_active": config.get("max_active_agents"),
            "last_spawn_at": _when(state.get("last_spawn_at")), "last_kind": state.get("last_kind")}


# ── rendering ───────────────────────────────────────────────────────────────

def _paint(text: str, colour: str | None, enabled: bool) -> str:
    return f"\033[{CODES[colour]}m{text}\033[0m" if enabled and colour else text


def _ago(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    if seconds < 86400:
        return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"
    return f"{seconds // 86400}d{seconds % 86400 // 3600:02d}h"


def _cut(text: str, width: int) -> str:
    return text if len(text) <= width else text[:max(0, width - 1)] + "…"


def _dot(state: str, colour: bool) -> str:
    symbol = "●" if state in ("running", "runner_starting") else "○" if state in ACTIVE else "·"
    return _paint(symbol, STATE_COLOUR.get(state, "grey"), colour)


def render_agents(rows: list[dict], now: datetime, colour: bool) -> str:
    if not rows:
        return _paint("No agents alive.", "dim", colour) + "\n"
    lines = [_paint(f"{len(rows)} agent{'s' if len(rows) != 1 else ''} alive", "bold", colour)]
    for row in rows:
        quiet = (now - row["last_activity"]).total_seconds() if row["last_activity"] else None
        head = (f" {_dot(row['state'], colour)} {_paint(row['name'], 'bold', colour)}"
                f"  {_paint(row['role'], 'magenta', colour)}"
                f"  {_paint(row['state'], STATE_COLOUR.get(row['state']), colour)}"
                f"  {_ago(row['age_seconds'])}")
        detail = [row["origin"]]
        if row["workspace"]:
            detail.append(row["workspace"])
        if row["model"]:
            detail.append(row["model"].removesuffix("-GGUF"))
        if row["state"] == "running":
            detail.append(f"{row['tool_calls']} tool calls")
            if quiet is not None:
                detail.append(f"last output {_ago(quiet)} ago")
        lines += [head, "     " + _paint(" · ".join(detail), "dim", colour),
                  "     " + _cut(row["what"], 100)]
        if row["state"] == "queued" and row["outcome"] and row["outcome"] != "Pending model-mediated routing.":
            lines.append("     " + _paint("waiting: " + _cut(row["outcome"], 90), "yellow", colour))
    return "\n".join(lines) + "\n"


def render_jobs(rows: list[dict], colour: bool) -> str:
    if not rows:
        return _paint("No jobs yet.", "dim", colour) + "\n"
    lines = []
    for row in rows:
        when = row["updated_at"].astimezone().strftime("%a %H:%M") if row["updated_at"] else "—"
        line = (f" {_dot(row['state'], colour)} {when}  {_cut(row['name'], 18):18}"
                f" {_paint(f'{row['role']:9}', 'magenta', colour)}"
                f" {_paint(f'{row['state']:10}', STATE_COLOUR.get(row['state']), colour)}"
                f" {_ago(row['age_seconds']):>6}  {_cut(row['what'], 60)}")
        lines.append(line)
        if row["state"] in ("failed", "rejected", "interrupted") and row["outcome"]:
            lines.append("      " + _paint(_cut(str(row["outcome"]), 100), "red", colour))
    return "\n".join(lines) + "\n"


def render_status(colour: bool) -> str:
    now = datetime.now(timezone.utc)
    report = health()
    mode_ok = report["resource_mode"] == "normal" and report["work_gate"] == "open"
    lines = [_paint("CointOS", "bold", colour) + "  " + (
        _paint("● healthy", "green", colour) if mode_ok and not report["paused"] else
        _paint("● paused", "yellow", colour) if report["paused"] else
        _paint(f"● {report['resource_mode']} / gate {report['work_gate']}", "red", colour))]
    if report["incident"]:
        lines.append(_paint(f"  incident {report['incident']}", "red", colour))
    lines.append("")
    lines.append(_paint("Models", "bold", colour))
    if report["backend_error"]:
        lines.append(_paint(f"  backend unreachable: {report['backend_error']}", "red", colour))
    for model in report["models"]:
        lanes = model["lanes"] or 1
        use = "busy" if model["busy"] else "idle"
        tags = " · pinned" if model["pinned"] else ""
        lines.append(f"  {_paint('▮' * lanes, 'green' if model['busy'] else 'grey', colour)} "
                     f"{model['model'].removesuffix('-GGUF'):22} {lanes} lane{'s' if lanes > 1 else ''}"
                     f" · {use}{tags}")
    lines.append("")
    rows = agents(now)
    lines.append(render_agents(rows, now, colour).rstrip())
    lines.append("")
    lines.append(_paint("Queues", "bold", colour))
    for queue in queues():
        parts = [f"{branch} {sum(c.values())}" + (
                 f" ({', '.join(f'{n} {s}' for s, n in sorted(c.items()))})" if c else "")
                 for branch, c in queue["counts"].items()]
        lines.append(f"  {queue['project']:14} " + ("  ".join(parts) if parts else
                                                   _paint("empty", "dim", colour)))
    spawn = spawner_state()
    last = (f"last spawned {spawn['last_kind']} {_ago((now - spawn['last_spawn_at']).total_seconds())} ago"
            if spawn["last_spawn_at"] else "nothing spawned yet")
    lines.append(f"  spawner {'on' if spawn['enabled'] else 'off'} · up to {spawn['max_active']} agents · {last}")
    lines.append("")
    down = [row["unit"] for row in services() if row["state"] not in ("active",)]
    lines.append(_paint("Services", "bold", colour) + "  " + (
        _paint("all up", "green", colour) if not down else
        _paint("down: " + ", ".join(unit.removeprefix("agent-") for unit in down), "red", colour)))
    return "\n".join(lines) + "\n"


def show(view: str, limit: int = 20) -> None:
    colour = sys.stdout.isatty()
    now = datetime.now(timezone.utc)
    if view == "agents":
        sys.stdout.write(render_agents(agents(now), now, colour))
    elif view == "jobs":
        sys.stdout.write(render_jobs(recent_jobs(limit, now), colour))
    else:
        sys.stdout.write(render_status(colour))


# ── web snapshot ────────────────────────────────────────────────────────────

def queue_items() -> list[dict]:
    """Every item leaf in the spawner projects' queues, with its status and headline."""
    try:
        config = json.loads((cli.ROOT / "config/spawner.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    from ecosystem.spawner import _status
    items = []
    for project in (Path(p).expanduser() for p in config.get("projects", [])):
        for branch in ("urgent", "queued", "drafted"):
            folder = project / ".knowledge/what/is" / branch
            for leaf in sorted(folder.rglob("*.md")) if folder.is_dir() else ():
                text = leaf.read_text(encoding="utf-8", errors="replace")
                if text.startswith("---"):
                    text = text.split("\n---", 1)[-1]
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                headline = next((line for line in lines if not line.lower().startswith("status:")), "")
                items.append({"project": project.name, "branch": branch, "path": str(leaf),
                              "name": leaf.stem.replace("-", " "), "status": _status(leaf) or "no status",
                              "headline": headline.strip("*# ")})
    return items


def coin() -> dict:
    """Coin's live inference (what it is running or waiting for) and recent exchanges."""
    active = []
    for path in (cli.ROOT / "state/inference-runs").glob("native-*.json"):
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if run.get("state") in ("waiting", "acquiring", "running"):
            active.append({"id": run.get("id"), "model": run.get("model"), "state": run.get("state"),
                           "placement": "live" if run.get("state") == "running" else "waiting",
                           "since": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)})
    turns = []
    for path in (cli.ROOT / "state/control-turns").glob("*.json"):
        try:
            turn = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        front, deep = turn.get("front_state"), turn.get("deep_state")
        if deep in ("queued", "running", "retry") or front in (None, "pending", "attempting", "generating", "ready", "sending"):
            status = "thinking"
        elif front == "failed" and deep in (None, "failed"):
            status = "failed"
        elif turn.get("followup_state") == "delivered" or front == "delivered":
            status = "replied"
        else:
            status = deep or front or "unknown"
        turns.append({"id": turn.get("id"), "received_at": _when(turn.get("received_at")),
                      "message": (turn.get("message") or "")[:80], "status": status,
                      "reply": (turn.get("followup") or turn.get("initial_response") or "")[:140]})
    turns.sort(key=lambda item: item["received_at"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return {"active": active, "turns": turns[:6]}


def _plain(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def snapshot() -> dict:
    """Everything the dashboard shows, as JSON-ready data."""
    now = datetime.now(timezone.utc)
    return _plain({"now": now, "health": health(), "agents": agents(now),
                   "jobs": recent_jobs(40, now), "queues": queue_items(),
                   "spawner": spawner_state(), "services": services(), "coin": coin()})
