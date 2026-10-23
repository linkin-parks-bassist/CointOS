"""Gateway keys: who is thinking. Coin has a fixed key, each agent run its own, and any other
key is the user. Agent keys persist so that runs outliving a daemon replacement are still known."""
from __future__ import annotations

import secrets

from cointos.config import KEYS, read_owned_json, write_json

OWNERS: dict[str, tuple[str, str]] = {}  # key -> (agent id, class)
ISSUED: dict[str, str] = {}  # agent id -> its key
ENDED: set[str] = set()  # keys of runs that have ended: their late requests are refused, never the user's


def _validate(data) -> dict:
    if (not isinstance(data, dict)
            or ("coin" in data and (not isinstance(data["coin"], str) or not data["coin"]))
            or not isinstance(data.get("agents", {}), dict)
            or any(not isinstance(agent, str) or not agent or not isinstance(key, str) or not key
                   for agent, key in data.get("agents", {}).items())):
        raise ValueError("invalid gateway key registry")
    values = list(data.get("agents", {}).values()) + ([data["coin"]] if "coin" in data else [])
    if len(set(values)) != len(values) or "coin" in data.get("agents", {}):
        raise ValueError("ambiguous gateway key ownership")
    return data


def stored() -> dict:
    """Only absence means an empty registry; never overwrite unreadable ownership."""
    return _validate(read_owned_json(KEYS, {}))


def unused(data: dict) -> str:
    """Allocate outside persisted, live and known ended ownership."""
    reserved = set(OWNERS) | set(ISSUED.values()) | ENDED | set(data.get("agents", {}).values())
    if "coin" in data:
        reserved.add(data["coin"])
    while True:
        key = secrets.token_urlsafe(24)
        if key not in reserved:
            return key


def load() -> None:
    """Coin's key, and the keys of agent runs still recorded from before a daemon start."""
    absent = object()
    data = read_owned_json(KEYS, absent)
    missing = data is absent
    data = _validate({} if missing else data)
    if 'coin' not in data:
        if not missing:
            raise ValueError('existing gateway registry is missing fixed Coin identity')
        data['coin'] = unused(data)
        write_json(KEYS, _validate(data), mode=0o600)
    OWNERS[data["coin"]] = ("coin", "coin")


def recorded() -> dict[str, str]:
    """Agent id -> key, as persisted."""
    return stored().get("agents", {})


def issue(agent_id: str, klass: str) -> str:
    data = stored()
    if agent_id == "coin" or klass == "coin" or agent_id in ISSUED or agent_id in data.get("agents", {}):
        raise ValueError(f"gateway identity {agent_id} already has an owner")
    key = unused(data)
    _persist(agent_id, key)
    adopt(agent_id, klass, key)
    return key


def adopt(agent_id: str, klass: str, key: str) -> None:
    if (agent_id == "coin" or klass == "coin" or key in ENDED
            or (key in OWNERS and OWNERS[key] != (agent_id, klass))
            or (agent_id in ISSUED and ISSUED[agent_id] != key)):
        raise ValueError("gateway key already owned or ended")
    OWNERS[key] = (agent_id, klass)
    ISSUED[agent_id] = key


def revoke(agent_id: str) -> None:
    key = ISSUED.pop(agent_id, "")
    if OWNERS.pop(key, None):
        ENDED.add(key)
    _persist(agent_id, None)


def ended(key: str) -> bool:
    """Whether a key belonged to a run that has ended. A stopping agent's process can still send a
    request after its run is released; served as the user's, it would take the lane first and
    re-read its whole conversation cold for a reply nobody reads."""
    return key in ENDED


def owner(key: str) -> tuple[str, str]:
    """(agent id, class) for a key; any key CointOS did not issue is the user's."""
    return OWNERS.get(key, ("user", "user"))


def _persist(agent_id: str, key: str | None) -> None:
    data = stored()
    agents = data.setdefault("agents", {})
    if key is None:
        agents.pop(agent_id, None)
    else:
        if agent_id in agents and agents[agent_id] != key:
            raise ValueError("gateway identity changed during key persistence")
        agents[agent_id] = key
    write_json(KEYS, _validate(data), mode=0o600)
