"""Operational configuration plus the separately managed project registry."""
from __future__ import annotations

import json
import os
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
    config = json.loads(path.read_text(encoding="utf-8"))
    registry_path = projects_path or (PROJECTS if path == CONFIG else path.with_name("projects.json"))
    registry = read_json(registry_path, {"projects": []})
    config["projects"] = registry["projects"]
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
