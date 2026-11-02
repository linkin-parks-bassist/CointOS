"""The complete record of an agent's runs, for whoever has to work out what went wrong.

OpenCode's own database holds every message, including the reasoning a run's event log omits.
It is read-only here, so a confined agent can use it. A transcript goes to a file because a long
run is far larger than anyone's context: read or search the parts that matter.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path


def database() -> Path:
    home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    return Path(home) / "opencode/opencode.db"


def sessions_of(task: dict, agents: Path) -> list[str]:
    """Every session the task ran in, oldest first as far as the record shows."""
    found = list(task.get("previous_sessions") or [])
    for run in sorted(agents.glob("*/run.json"), key=lambda path: path.stat().st_mtime):
        try:
            data = json.loads(run.read_text())
        except (OSError, ValueError):
            continue
        if data.get("task") == task["id"] and data.get("session"):
            found.append(data["session"])
    if task.get("session"):
        found.append(task["session"])
    return list(dict.fromkeys(found))


def _part(part: dict) -> list[str]:
    kind = part.get("type")
    if kind == "reasoning" and part.get("text"):
        return ["[thinking]", part["text"]]
    if kind == "text" and part.get("text"):
        return [part["text"]]
    if kind == "tool":
        state = part.get("state") or {}
        lines = [f"[tool {part.get('tool')} {state.get('status')}]", "input: " + json.dumps(state.get("input"), ensure_ascii=False)]
        result = state.get("output") if "output" in state else state.get("error")
        return lines + (["output:", str(result)] if result is not None else [])
    return [f"[{kind}]"] if kind == "compaction" else []


def render(path: Path, sessions: list[str]) -> tuple[str, int]:
    """The sessions as readable text, and how many messages they hold."""
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    try:
        lines, count = [], 0
        for session in sessions:
            lines.append(f"===== session {session} =====")
            messages = connection.execute("select id, data from message where session_id = ? order by id", (session,)).fetchall()
            if not messages:
                lines.append("(no messages on record)")
            for identifier, data in messages:
                count += 1
                lines.append(f"\n--- {json.loads(data).get('role')} {identifier} ---")
                parts = connection.execute("select data from part where message_id = ? order by id", (identifier,))
                for (part,) in parts:
                    lines.extend(_part(json.loads(part)))
        return "\n".join(lines) + "\n", count
    finally:
        connection.close()
