from __future__ import annotations

from pathlib import Path

from ecosystem import cli
from survival.time_policy import (
    REQUIRED_KEYS,
    _validate,
    _value,
    adopt_last_known_good,
    read_accepted_policy,
    seconds,
    validate,
)
from survival import time_policy as _owner


CONFIG_PATH = cli.ROOT / "config/time.cfg"


def load(path: Path = CONFIG_PATH,
         required: dict[str, set[str]] = REQUIRED_KEYS) -> dict[str, dict[str, float]]:
    return _owner.load(path, required)


def reload_if_changed(active: dict, active_mtime_ns: int,
                      path: Path = CONFIG_PATH) -> tuple[dict, int, str | None]:
    return _owner.reload_if_changed(active, active_mtime_ns, path)
