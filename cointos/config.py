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
    if type(config.get('factory_enabled', True)) is not bool:
        raise ValueError('factory_enabled must be a boolean')
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


def identity(config: dict) -> str:
    """The name this installation's Coin uses as its conversation owner.

    A single installation keeps the historical `coin`; each Cointel instance names itself so
    three Coins sharing one model runner cannot select, resume or release each other's state."""
    value = config.get('coin', {}).get('identity') or 'coin'
    if not isinstance(value, str) or not value or not all(c.isalnum() or c in '-_' for c in value):
        raise ValueError('coin.identity must be a short alphanumeric slug')
    return value


def coin_name(config: dict) -> str:
    """The name Coin calls itself; the Telegram bot and prompt identity use it."""
    value = config.get('coin', {}).get('name') or 'Coin'
    if not isinstance(value, str) or not value.strip():
        raise ValueError('coin.name must be a nonempty string')
    return value.strip()


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
    def valid_artifact(value):
        return (isinstance(value, dict) and set(value) == {'commit', 'base'}
                and all(isinstance(v, str) and len(v) == 40 and all(c in '0123456789abcdef' for c in v)
                        for v in value.values()))
    owners = [(record, record.get('project')) for record in previous.get('queue', {}).values()]
    owners += [(task, task.get('place')) for task in previous.get('tasks', {}).values()]
    for record, place in owners:
        if 'carried_work' in record:
            references = record['carried_work']
            if not isinstance(references, list):
                raise ValueError('invalid carried work references')
            for reference in references:
                if (not isinstance(reference, dict) or set(reference) != {'task', 'version', 'stage', 'run'}
                        or not isinstance(reference['task'], str)
                        or not reference['task'].startswith(str(place) + ':')
                        or reference['stage'] not in (None, 'skeleton', 'test-contract', 'implementation', 'integration')
                        or (reference['version'] is not None and (type(reference['version']) is not int or reference['version'] < 1))
                        or (reference['run'] is not None and (not isinstance(reference['run'], str) or not reference['run']))):
                    raise ValueError('invalid carried work reference')
        if 'preserved_artifact' in record:
            artifact = record['preserved_artifact']
            if not valid_artifact(artifact):
                raise ValueError('invalid preserved work artifact')
    for task in previous.get('tasks', {}).values():
        if 'material_snapshots' in task:
            cache = task['material_snapshots']
            if (not isinstance(cache, dict) or any(not isinstance(k, str) or len(k) != 64
                    or any(c not in '0123456789abcdef' for c in k) or not valid_artifact(v) for k, v in cache.items())):
                raise ValueError('invalid preserved material cache')
        if 'session_store' in task and (not isinstance(task['session_store'], str) or not task['session_store']):
            raise ValueError('invalid task session_store')
        value = task.get('scheduling_weight')
        if 'scheduling_weight' in task and (type(value) not in (int, float) or not math.isfinite(value) or value <= 0):
            raise ValueError('invalid task scheduling_weight')
        if 'handoff_intent' in task:
            intent = task['handoff_intent']
            fields = {'run', 'version', 'commit', 'parent', 'summary', 'items', 'records', 'before', 'evidence'}
            if not isinstance(intent, dict) or set(intent) != fields or task.get('role') != 'manager':
                raise ValueError('invalid planning handoff intent')
            if any(not isinstance(task.get(k), str) or not task[k] for k in ('id', 'place')):
                raise ValueError('invalid planning handoff owner')
            if (not isinstance(intent['run'], str) or not intent['run']
                    or (intent['version'] is not None and (type(intent['version']) is not int or intent['version'] < 1))
                    or not isinstance(intent['summary'], str) or not intent['summary'].strip()
                    or not isinstance(intent['items'], list) or any(not isinstance(i, dict) for i in intent['items'])
                    or not isinstance(intent['evidence'], dict)
                    or any(not isinstance(intent[k], dict) for k in ('records', 'before'))):
                raise ValueError('invalid planning handoff intent fields')
            if any(not isinstance(intent[k], str) or len(intent[k]) != 40
                   or any(c not in '0123456789abcdef' for c in intent[k]) for k in ('commit', 'parent')):
                raise ValueError('invalid planning handoff artifact identity')
            if intent['records'].keys() != intent['before'].keys():
                raise ValueError('invalid planning handoff record set')
            for key, record in intent['records'].items():
                if (not isinstance(record, dict) or record.get('project') != task.get('place')
                        or not isinstance(record.get('item'), str) or key != f"{record['project']}:{record['item']}"
                        or record.get('proposed_by') != task.get('id')
                        or (intent['before'][key] is not None and not isinstance(intent['before'][key], dict))):
                    raise ValueError('invalid planning handoff child identity')
    for identifier, entry in previous.get('snapshot_garbage', {}).items():
        backend, tier, name, size = (entry.get(k) for k in ('backend', 'tier', 'name', 'bytes'))
        if (backend not in ('llama', 'gufo') or tier not in ('memory', 'disk')
                or not isinstance(name, str)
                or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-' for c in name)
                or identifier != f'{backend}:{tier}:{name}'
                or type(size) not in (int, float) or not math.isfinite(size) or size < 0):
            raise ValueError('invalid ledger snapshot_garbage entry')
    return previous
