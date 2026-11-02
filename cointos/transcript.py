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


# ---------------------------------------------------------------- indexed reading

SHOWN_CHARS = 40000


def entries(path: Path, sessions: list[str]) -> list[dict]:
    """Every thought, reply, tool call and user message in order, numbered, with its turn."""
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    found, turn = [], 0
    try:
        for session in sessions:
            messages = connection.execute("select id, data from message where session_id = ? order by id", (session,)).fetchall()
            for identifier, data in messages:
                role = json.loads(data).get("role")
                turn += role == "assistant"
                for (part,) in connection.execute("select data from part where message_id = ? order by id", (identifier,)):
                    part = json.loads(part)
                    kind = part.get("type")
                    if kind == "reasoning" and part.get("text"):
                        found.append({"turn": turn, "kind": "thought", "text": part["text"]})
                    elif kind == "text" and part.get("text"):
                        found.append({"turn": turn, "kind": "reply" if role == "assistant" else "user", "text": part["text"]})
                    elif kind == "tool":
                        found.append({"turn": turn, "kind": "tool", "text": "\n".join(_part(part))})
                    elif kind == "compaction":
                        found.append({"turn": turn, "kind": "compaction", "text": "[compaction]"})
    finally:
        connection.close()
    return found


def coin_entries(path: Path) -> list[dict]:
    """Coin's own recent turns, from the journal its viewers read."""
    found, turn = [], 0
    for line in path.read_text(errors="replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        kind = row.get("kind")
        turn += kind == "user"
        if kind == "user":
            found.append({"turn": turn, "kind": "user", "text": str(row.get("content") or row.get("text") or "")})
        elif kind == "tool":
            found.append({"turn": turn, "kind": "tool", "text": f"[tool {row.get('name')}]\ninput: "
                          + json.dumps(row.get("input"), ensure_ascii=False) + "\noutput:\n" + str(row.get("output"))})
        elif kind == "assistant":
            if row.get("reasoning"):
                found.append({"turn": turn, "kind": "thought", "text": row["reasoning"]})
            if row.get("content"):
                found.append({"turn": turn, "kind": "reply", "text": str(row["content"])})
    return found


def view(found: list[dict], *, show: str | None = None, kind: str | None = None, turn: int | None = None,
         grep: str | None = None, last: int = 40) -> str:
    """An index of the entries, or the full text of a range of them (`show` as N or N-M)."""
    numbered = list(enumerate(found, 1))
    if show:
        low, _, high = show.partition("-")
        low, high = int(low), int(high or low)
        text = "\n\n".join(f"#{n} turn {e['turn']} {e['kind']}\n{e['text']}" for n, e in numbered if low <= n <= high)
        return text[:SHOWN_CHARS] + (f"\n[cut at {SHOWN_CHARS} characters; ask for a smaller range]" if len(text) > SHOWN_CHARS else "")
    chosen = [(n, e) for n, e in numbered if (not kind or e["kind"] == kind) and (turn is None or e["turn"] == turn)
              and (not grep or grep.lower() in e["text"].lower())]
    head = f"{len(found)} entries, {found[-1]['turn'] if found else 0} turns; showing {min(last, len(chosen))} of {len(chosen)} that match. Read one with show N or N-M."
    return "\n".join([head] + [f"#{n} t{e['turn']} {e['kind']} {len(e['text']):,} chars: " + " ".join(e["text"].split())[:100]
                               for n, e in chosen[-last:]])
