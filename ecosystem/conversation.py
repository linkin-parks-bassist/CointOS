"""Private, bounded, per-Telegram-user conversation memory."""
from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from pathlib import Path

from ecosystem import cli

_CANONICAL_TURN_ID = re.compile(r"telegram-(0|[1-9][0-9]*)")


def _require_canonical_identity(identity: str) -> str:
    if _CANONICAL_TURN_ID.fullmatch(identity) is None:
        raise ValueError(f"invalid canonical turn identity: {identity!r}")
    return identity


def path_for(user_id: int) -> Path:
    directory = cli.ROOT / "state/conversations"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"telegram-{user_id}.jsonl"


def append(user_id: int, role: str, content: str, source_id: str | None = None,
           reply_to: str | None = None) -> None:
    if role not in {"user", "assistant"}:
        raise ValueError("invalid conversation role")
    if source_id is not None:
        _require_canonical_identity(source_id)
    if reply_to is not None:
        _require_canonical_identity(reply_to)
    path = path_for(user_id)
    if source_id and contains(user_id, source_id):
        return
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
        record = {"at": cli.now(), "role": role, "content": content, "record_version": 2}
        if source_id:
            record["source_id"] = source_id
        if reply_to is not None:
            record["reply_to"] = reply_to
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        stream.flush(); os.fsync(stream.fileno())


def contains(user_id: int, source_id: str) -> bool:
    path = path_for(user_id)
    if not path.exists():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and json.loads(line).get("source_id") == source_id:
            return True
    return False


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


def recent_before(user_id: int, source_id: str, max_messages: int = 20,
                  max_characters: int = 12000) -> list[dict[str, str]]:
    path = path_for(user_id)
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get("source_id") == source_id:
            break
        entries.append(entry)
    selected = []
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


def _projected_row(user_id: int, entry: dict, content: str,
                   lifecycle_for: Callable[[str], dict | None]) -> dict:
    source_id = entry.get("source_id")
    reply_to = entry.get("reply_to")
    lifecycle = None
    if source_id is not None:
        owner = lifecycle_for(source_id)
        if isinstance(owner, dict):
            lifecycle = owner.get("lifecycle")
    return {
        "id": source_id,
        "role": entry["role"],
        "content": content,
        "lifecycle": lifecycle,
        "sender": user_id,
        "reply_to": reply_to,
        "provenance": {
            "kind": "ingress" if entry["role"] == "user" else "assistant",
            "source_id": source_id,
            "reply_to": reply_to,
        },
    }


def recent_state(user_id: int, lifecycle_for: Callable[[str], dict | None],
                 max_messages: int = 20, max_characters: int = 12000) -> list[dict]:
    path = path_for(user_id)
    if not path.exists():
        return []
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    selected: list[dict] = []
    characters = 0
    for entry in reversed(entries):
        content = str(entry.get("content", ""))
        if selected and characters + len(content) > max_characters:
            break
        selected.append(_projected_row(user_id, entry, content[:max_characters], lifecycle_for))
        characters += len(content)
        if len(selected) >= max_messages:
            break
    return list(reversed(selected))


def forget(user_id: int) -> None:
    path_for(user_id).unlink(missing_ok=True)
    cli.audit("conversation.forgotten", user_id=user_id)
