"""Private, bounded, per-Telegram-user conversation memory."""
from __future__ import annotations

import json
import os
from pathlib import Path

from ecosystem import cli


def path_for(user_id: int) -> Path:
    directory = cli.ROOT / "state/conversations"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"telegram-{user_id}.jsonl"


def append(user_id: int, role: str, content: str) -> None:
    if role not in {"user", "assistant"}:
        raise ValueError("invalid conversation role")
    path = path_for(user_id)
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
        stream.write(json.dumps({"at": cli.now(), "role": role, "content": content}, ensure_ascii=False) + "\n")
        stream.flush(); os.fsync(stream.fileno())


def recent(user_id: int, max_messages: int = 20, max_characters: int = 12000) -> list[dict[str, str]]:
    path = path_for(user_id)
    if not path.exists():
        return []
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    selected: list[dict[str, str]] = []
    characters = 0
    for entry in reversed(entries):
        content = str(entry.get("content", ""))
        if selected and characters + len(content) > max_characters:
            break
        selected.append({"role": entry["role"], "content": content[:max_characters]})
        characters += len(content)
        if len(selected) >= max_messages:
            break
    return list(reversed(selected))


def forget(user_id: int) -> None:
    path_for(user_id).unlink(missing_ok=True)
    cli.audit("conversation.forgotten", user_id=user_id)

