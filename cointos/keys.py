"""Gateway keys: who is thinking. Coin has a fixed key, each agent run its own, and any other
key is David. Agent keys persist so that runs outliving a daemon replacement are still known."""
from __future__ import annotations

import secrets

from cointos.config import KEYS, read_json, write_json

OWNERS: dict[str, tuple[str, str]] = {}  # key -> (agent id, class)
ISSUED: dict[str, str] = {}  # agent id -> its key


def load() -> None:
    """Coin's key, and the keys of agent runs still recorded from before a daemon start."""
    stored = read_json(KEYS, {})
    if "coin" not in stored:
        stored["coin"] = secrets.token_urlsafe(24)
        write_json(KEYS, stored, mode=0o600)
    OWNERS[stored["coin"]] = ("coin", "coin")


def recorded() -> dict[str, str]:
    """Agent id -> key, as persisted."""
    return read_json(KEYS, {}).get("agents", {})


def issue(agent_id: str, klass: str) -> str:
    key = secrets.token_urlsafe(24)
    adopt(agent_id, klass, key)
    _persist(agent_id, key)
    return key


def adopt(agent_id: str, klass: str, key: str) -> None:
    OWNERS[key] = (agent_id, klass)
    ISSUED[agent_id] = key


def revoke(agent_id: str) -> None:
    OWNERS.pop(ISSUED.pop(agent_id, ""), None)
    _persist(agent_id, None)


def owner(key: str) -> tuple[str, str]:
    """(agent id, class) for a key; any key CointOS did not issue is David's."""
    return OWNERS.get(key, ("user", "user"))


def _persist(agent_id: str, key: str | None) -> None:
    stored = read_json(KEYS, {})
    agents = stored.setdefault("agents", {})
    if key is None:
        agents.pop(agent_id, None)
    else:
        agents[agent_id] = key
    write_json(KEYS, stored, mode=0o600)
