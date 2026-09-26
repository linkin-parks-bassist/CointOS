"""The one place every number comes from: `config/cointos.json`."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = Path(os.environ.get("COINTOS_CONFIG", ROOT / "config/cointos.json"))
STATE = Path(os.environ.get("COINTOS_STATE", ROOT / "state"))
LEDGER = STATE / "cointos.json"
KEYS = STATE / "keys.json"


def load(path: Path = CONFIG) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    for project in config["projects"]:
        project["path"] = str(Path(project["path"]).expanduser())
        project.setdefault("main_branch", "main")
    return config


def api_url(config: dict) -> str:
    return f"http://127.0.0.1:{config['port']}"


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
