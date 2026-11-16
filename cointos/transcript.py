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
    for _, data in task_runs(task, agents):
        if data.get('session'):
            found.append(data['session'])
    if task.get("session"):
        found.append(task["session"])
    return list(dict.fromkeys(found))


def task_runs(task, agents):
    found = []
    for run in sorted(agents.glob('*/run.json'), key=lambda path: path.stat().st_mtime):
        try:
            data = json.loads(run.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        identity = data.get('task')
        if (identity.get('id') if isinstance(identity, dict) else identity) == task['id']:
            found.append((run.parent.name, data))
    return found


def task_sources(task, agents):
    """Select each retained session's store without substituting stale current history."""
    runs = task_runs(task, agents)
    owner = task.get('agent') or (task.get('receipt') or {}).get('run') or task.get('preserved_run')
    current = next((data.get('agent_data') for name, data in reversed(runs) if name == owner), None)
    current = current or task.get('session_store')
    stores = [current, *(data.get('agent_data') for _, data in reversed(runs))]
    paths = list(dict.fromkeys([Path(store) / 'data/opencode/opencode.db' for store in stores if store] + [database()]))
    sessions = sessions_of(task, agents)
    selected, missing = {}, []
    for session in sessions:
        if session == task.get('session') and current:
            authoritative = Path(current) / 'data/opencode/opencode.db'
            if not authoritative.is_file():
                raise ValueError('the current trace store is unavailable; preserve run evidence for recovery')
            selected[session] = authoritative
            continue
        for path in paths:
            if not path.is_file():
                continue
            connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=10)
            try:
                table = 'session_message' if native_v2(connection) else 'message'
                if connection.execute(f'select 1 from {table} where session_id = ? limit 1', (session,)).fetchone():
                    selected[session] = path
                    break
            finally:
                connection.close()
        else:
            missing.append(session)
    return sessions, selected, missing


def read_task(task, agents, *, export=False, public=False, **options):
    try:
        sessions, paths, missing = task_sources(task, agents)
        if export:
            text, messages = render(paths, sessions, public=public)
            result = {'text': text, 'messages': messages, 'sessions': len(sessions)}
        else:
            result = {'text': view(entries(paths, sessions, public=public), **options)}
        if missing:
            result['text'] = f'Historical coverage incomplete: {len(missing)} session(s) unavailable.\n' + result['text']
        return result
    except sqlite3.Error as error:
        raise ValueError('the selected trace could not be read; preserve run evidence for recovery') from error


def _part(part: dict, *, public=False, role=None) -> list[str]:
    kind = part.get("type")
    if kind == "reasoning" and part.get("text"):
        return ["[thinking]", part["text"]]
    if kind == "text" and part.get("text"):
        return [part["text"]]
    if kind == 'control':
        return ['[system control]', part['text']]
    if kind == "tool":
        state = part.get("state") or {}
        lines = [f"[tool {part.get('tool')} {state.get('status')}]", "input: " + json.dumps(state.get("input"), ensure_ascii=False)]
        result = state.get("output") if "output" in state else state.get("error")
        if (public and role == 'assistant' and state.get('status') == 'error'
                and 'output' not in state
                and part.get('tool') in {'bash', 'read', 'write', 'edit', 'glob', 'grep', 'list', 'multiedit', 'apply_patch'}
                and isinstance(result, str) and result.startswith(
                    'The user has specified a rule which prevents you from using this specific tool call.')):
            result = ("This operation is outside this run's permitted scope. Use assigned files and declared "
                      "CointOS controls; report a required blocked step through normal recovery.")
        return lines + (["output:", str(result)] if result is not None else [])
    if kind == 'compaction':
        return [f"[compaction {part.get('status', '')}]".replace(' ]', ']'), *([part['summary']] if part.get('summary') else [])]
    return []


def native_v2(connection):
    return connection.execute("select 1 from sqlite_master where type='table' and name='session_v2'").fetchone() is not None


def native_messages(connection, session):
    for identifier, kind, raw in connection.execute('select id,type,data from session_message where session_id=? order by seq', (session,)):
        message = {**json.loads(raw), 'id': identifier, 'type': kind}
        if kind == 'assistant':
            pending = [{**json.loads(raw), 'type': typ} for typ, raw in connection.execute(
                'select type,data from session_part where message_id=? order by ordinal', (identifier,))]
            if pending:
                message['content'] = pending
        yield message


def stored_messages(connection, session):
    """Read native projections without starting a server or mutating either store."""
    if not native_v2(connection):
        for identifier, data in connection.execute('select id,data from message where session_id=? order by id', (session,)):
            parts = [json.loads(row[0]) for row in connection.execute('select data from part where message_id=? order by id', (identifier,))]
            yield identifier, json.loads(data).get('role'), parts
        return
    for data in native_messages(connection, session):
        identifier, kind = data['id'], data['type']
        parts = []
        if kind == 'user':
            parts = [{'type': 'text', 'text': data.get('text', '')}]
        elif kind == 'assistant':
            for part in data.get('content', []):
                if part['type'] != 'tool':
                    parts.append(part)
                    continue
                status = part.get('state', {})
                converted = {**status}
                if 'content' in status:
                    converted['output'] = '\n'.join(c.get('text', '') if c['type'] == 'text'
                                                   else '[file] ' + str(c.get('uri', '')) for c in status['content'])
                if 'error' in status:
                    converted['error'] = json.dumps(status['error'], ensure_ascii=False)
                parts.append({**part, 'tool': part['name'], 'state': converted})
            if data.get('error'):
                parts.append({'type': 'control', 'text': json.dumps(data['error'], ensure_ascii=False)})
        elif kind == 'compaction':
            parts = [{'type': 'compaction', **data}]
        elif kind in ('synthetic', 'system'):
            parts = [{'type': 'control', 'text': data.get('text', '')}]
        elif kind == 'idle':
            parts = [{'type': 'control', 'text': 'Execution ' + data.get('outcome', 'unknown')}]
        else:
            parts = [{'type': 'control', 'text': kind + ': ' + json.dumps(data, ensure_ascii=False)}]
        yield identifier, kind, parts


def render(path: Path, sessions: list[str], *, public=False) -> tuple[str, int]:
    """The sessions as readable text, and how many messages they hold."""
    if isinstance(path, dict):
        pieces, count = [], 0
        for session in sessions:
            if session not in path:
                pieces.append(f'===== session {session} =====\n(no messages on record)\n')
                continue
            text, messages = render(path[session], [session], public=public)
            pieces.append(text)
            count += messages
        return ''.join(pieces), count
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    try:
        connection.execute('begin')  # Message consolidation and streamed parts share one snapshot.
        lines, count = [], 0
        for session in sessions:
            lines.append(f"===== session {session} =====")
            messages = list(stored_messages(connection, session))
            if not messages:
                lines.append("(no messages on record)")
            for identifier, role, parts in messages:
                count += 1
                lines.append(f"\n--- {role} {identifier} ---")
                for part in parts:
                    lines.extend(_part(part, public=public, role=role))
        return "\n".join(lines) + "\n", count
    finally:
        connection.close()


# ---------------------------------------------------------------- indexed reading

SHOWN_CHARS = 40000


def entries(path: Path, sessions: list[str], *, public=False) -> list[dict]:
    """Every thought, reply, tool call and user message in order, numbered, with its turn."""
    if isinstance(path, dict):
        found, turn = [], 0
        for session in sessions:
            if session in path:
                chunk, turn = _entries(path[session], [session], turn, public=public)
                found += chunk
        return found
    return _entries(path, sessions, public=public)[0]


def _entries(path, sessions, turn=0, *, public=False):
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    found = []
    try:
        connection.execute('begin')
        for session in sessions:
            for identifier, role, parts in stored_messages(connection, session):
                turn += role == "assistant"
                for part in parts:
                    kind = part.get("type")
                    if kind == "reasoning" and part.get("text"):
                        found.append({"turn": turn, "kind": "thought", "text": part["text"]})
                    elif kind == "text" and part.get("text"):
                        found.append({"turn": turn, "kind": "reply" if role == "assistant" else "user", "text": part["text"]})
                    elif kind == "tool":
                        found.append({"turn": turn, "kind": "tool", "text": "\n".join(_part(part, public=public, role=role))})
                    elif kind == "compaction":
                        found.append({"turn": turn, "kind": "compaction", "text": '\n'.join(_part(part))})
                    elif kind == 'control':
                        found.append({'turn': turn, 'kind': 'system', 'text': part['text']})
    finally:
        connection.close()
    return found, turn


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
