"""Operational configuration plus the separately managed project registry."""
from __future__ import annotations

import json
import math
import os
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path(os.environ.get("COINTOS_CONFIG", ROOT / "config/cointos.json"))
PROJECTS = Path(os.environ.get("COINTOS_PROJECTS", ROOT / "config/projects.json"))
STATE = Path(os.environ.get("COINTOS_STATE", ROOT / "state"))
LEDGER = STATE / "cointos.json"
KEYS = STATE / "keys.json"

# A live installation replaces cointosd but deliberately preserves OpenCode, Coin and
# model-server processes. These fields identify the gateway/model processes that the new
# daemon must adopt exactly as they are. Other settings may be daemon policy or launch-time
# policy retained by an existing child; changing them does not invalidate that survivor.
LIVE_PROCESS_IDENTITY = (
    ("backend",),
    ("lemonade",),
    ("snapshots",),
    ("server_cgroup",),
    ("port",),
    ("work_model",),
    ("models",),
)


def load(path: Path = CONFIG, projects_path: Path | None = None) -> dict:
    config = read_owned_json(path)
    if not isinstance(config, dict):
        raise ValueError("invalid operational configuration")
    if 'history_trim_messages' in config.get('coin', {}):
        limit, trim = config['coin'].get('history_messages'), config['coin']['history_trim_messages']
        if type(limit) is not int or type(trim) is not int or not 1 <= trim < limit:
            raise ValueError('Coin history requires 1 <= history_trim_messages < history_messages')
    registry_path = projects_path or (PROJECTS if path == CONFIG else path.with_name("projects.json"))
    registry = read_owned_json(registry_path, {"projects": []})
    if not isinstance(registry, dict) or "projects" not in registry:
        raise ValueError("invalid project registry")
    config["projects"] = project_entries(registry["projects"])
    for place in config["projects"] + config["trees"]:
        place["path"] = str(Path(place["path"]).expanduser())
    config["projects"].sort(key=lambda p: (p.get("priority", 100), p["name"].lower()))
    return config


def api_url(config: dict) -> str:
    return f"http://127.0.0.1:{config['port']}"


def live_incompatibilities(installed: dict, candidate: dict) -> list[str]:
    """Configuration paths whose change invalidates processes preserved by a live install."""
    different = []
    for path in LIVE_PROCESS_IDENTITY:
        before, after = installed, candidate
        for part in path:
            before = before.get(part) if isinstance(before, dict) else None
            after = after.get(part) if isinstance(after, dict) else None
        if before != after:
            different.append(".".join(path))
    return different


def managed_trees(config: dict) -> list[dict]:
    """Every knowledge tree CointOS owns: explicit trees plus registered projects."""
    trees = {tree["name"]: tree for tree in config["trees"]}
    for project in config["projects"]:
        tree_path = Path(project["path"]) / project.get("tree", ".knowledge")
        if not tree_path.is_dir():
            continue
        trees.setdefault(project["name"], {"name": project["name"], "path": project["path"],
                                            "main_branch": project["main_branch"],
                                            "tree": project.get("tree", ".knowledge")})
    return list(trees.values())


def write_json(path: Path, value, mode: int = 0o644) -> None:
    """Write atomically: readers see the old or the new file, never half of one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=1, sort_keys=True)
        stream.write("\n")
    os.replace(temporary, path)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _fields(pairs) -> dict:
    data = dict(pairs)
    if len(data) != len(pairs):
        raise ValueError("duplicate JSON fields")
    return data


def read_owned_text(path: Path, default=None):
    """Read one regular, non-symlink authority file; only absence uses defaults."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NOCTTY)
    except FileNotFoundError:
        return default
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(f"authority file is not regular: {path}")
        stream = os.fdopen(descriptor, "r", encoding="utf-8", newline="")
    except BaseException:
        os.close(descriptor)
        raise
    with stream:
        return stream.read()


def read_owned_json(path: Path, default=None):
    absent = object()
    text = read_owned_text(path, absent)
    return default if text is absent else json.loads(text, object_pairs_hook=_fields)


def project_entries(entries) -> list[dict]:
    if (not isinstance(entries, list)
            or any(not isinstance(entry, dict)
                   or not isinstance(entry.get("name"), str)
                   or not isinstance(entry.get("path"), str) for entry in entries)):
        raise ValueError("invalid project registry entries")
    return entries


def validate_ledger(previous) -> dict:
    """Validate retained containers before startup or migration mutates anything."""
    if not isinstance(previous, dict):
        raise ValueError("invalid ledger root")
    for name in ("tasks", "queue", "agents", "snapshots", "snapshot_garbage", "system_contexts",
                 "dependency_problems", "check_incidents", "cadence", "coin"):
        if name in previous and not isinstance(previous[name], dict):
            raise ValueError(f"invalid ledger {name}")
    for name in ("messages", "history", "alerts"):
        if name in previous and not isinstance(previous[name], list):
            raise ValueError(f"invalid ledger {name}")
    for name in ("tasks", "agents", "queue", "snapshots", "snapshot_garbage"):
        if any(not isinstance(entry, dict) for entry in previous.get(name, {}).values()):
            raise ValueError(f"invalid ledger {name} entry")
    for identifier, entry in previous.get('snapshot_garbage', {}).items():
        backend, tier, name, size = (entry.get(k) for k in ('backend', 'tier', 'name', 'bytes'))
        if (backend not in ('llama', 'gufo') or tier not in ('memory', 'disk')
                or not isinstance(name, str)
                or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-' for c in name)
                or identifier != f'{backend}:{tier}:{name}'
                or type(size) not in (int, float) or not math.isfinite(size) or size < 0):
            raise ValueError('invalid ledger snapshot_garbage entry')
    return previous
