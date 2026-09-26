"""Loading models through Lemonade in their configured shapes, and reading what loaded."""
from __future__ import annotations

import json
import shlex
import urllib.request


def _call(config: dict, method: str, path: str, body: dict | None = None, timeout: float = 10):
    request = urllib.request.Request(
        config["lemonade"] + path, method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def health(config: dict) -> dict[str, dict]:
    """Lemonade's view of every loaded model, by name."""
    return {entry["model_name"]: entry for entry in _call(config, "GET", "/api/v1/health")["all_models_loaded"]}


def wanted_args(shape: dict) -> str:
    return f"--parallel {shape['lanes']} {shape['args']}"


def mismatches(shape: dict, entry: dict | None) -> list[str]:
    """How a loaded model differs from its configured shape (empty when it matches)."""
    if entry is None or not entry.get("loaded"):
        return ["not loaded"]
    argv = entry.get("launch_command") or []
    problems = []

    def value(flag):
        return argv[argv.index(flag) + 1] if flag in argv[:-1] else None

    if value("--ctx-size") != str(shape["ctx_size"]):
        problems.append(f"ctx-size {value('--ctx-size')} != {shape['ctx_size']}")
    wanted = shlex.split(wanted_args(shape))
    for index, token in enumerate(wanted):
        if not token.startswith("--"):
            continue
        following = wanted[index + 1] if index + 1 < len(wanted) and not wanted[index + 1].startswith("--") else None
        if token not in argv:
            problems.append(f"{token} missing")
        elif following is not None and value(token) != following:
            problems.append(f"{token} {value(token)} != {following}")
    flags = {token for token in wanted if token.startswith("--")}
    for flag in ("--reasoning-budget",):
        if flag in argv and flag not in flags:
            problems.append(f"unexpected {flag}")
    return problems


def load(config: dict, name: str) -> dict:
    """Load `name` in its configured shape (reloading if the shape differs) and return its health entry."""
    shape = config["models"][name]
    current = health(config).get(name)
    if not mismatches(shape, current):
        return current
    if current is not None and current.get("loaded"):
        unload(config, name)
    _call(config, "POST", "/v1/load", {
        "model_name": name, "ctx_size": shape["ctx_size"], "llamacpp_args": wanted_args(shape),
        "merge_args": False, "save_options": True, "pinned": shape.get("pinned", False),
    }, timeout=900)
    entry = health(config).get(name)
    problems = mismatches(shape, entry)
    if problems:
        raise RuntimeError(f"{name} loaded in the wrong shape: {'; '.join(problems)}")
    return entry


def unload(config: dict, name: str) -> None:
    _call(config, "POST", "/v1/unload", {"model_name": name}, timeout=300)


def gpu_memory_gb() -> float:
    """GPU memory in use, summed over cards (unified memory, so it is host memory too)."""
    from pathlib import Path
    total = 0
    for path in Path("/sys/class/drm").glob("card*/device/mem_info_gtt_used"):
        try:
            total += int(path.read_text())
        except (OSError, ValueError):
            pass
    return round(total / 1e9, 1)
