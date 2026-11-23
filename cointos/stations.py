"""A station is where an agent works and what it can reach: (directory, tools).

Every agent has one. The directory is its task's `worktree`, so a factory agent's station is
its checkout; `tools` names the configured MCP servers it may use beyond the knowledge-tree and
CointOS tools every agent has. An Operator can be stationed in any directory, and its writes are
confined there. Coin's station is the user's home with everything.
"""
from __future__ import annotations

import json
from pathlib import Path

from cointos.config import ROOT

EVERYTHING = '*'
NATIVE_CONFIG = Path.home() / '.config/opencode2/opencode/opencode.json'
LEGACY_CONFIG = Path.home() / '.config/opencode/opencode.json'
GLOBAL_CONFIG = NATIVE_CONFIG if NATIVE_CONFIG.is_file() else LEGACY_CONFIG
# Always present, so never a grant.
BASE = frozenset(('knowledgetrees', 'cointos'))
COIN = {'directory': str(Path.home()), 'tools': [EVERYTHING]}


def servers() -> dict:
    """The MCP servers the user has configured; a missing or unreadable config has none.

    OpenCode 2 stores them under `mcp.servers` and marks exclusions with `disabled`.
    Its V1 shape uses `mcp.<name>` with `enabled`; both are accepted here.
    """
    try:
        config = json.loads(GLOBAL_CONFIG.read_text())
    except (OSError, ValueError):
        return {}
    mcp = config.get('mcp')
    if not isinstance(mcp, dict):
        return {}
    if isinstance(mcp.get('servers'), dict):
        normalized = {}
        for name, server in mcp['servers'].items():
            if not isinstance(server, dict):
                continue
            server = dict(server)
            if 'disabled' in server:
                server['enabled'] = not server.pop('disabled')
            if server.get('enabled', True):
                normalized[name] = server
        return normalized
    return mcp


def tools(requested) -> list[str]:
    """A normalized tool grant. A refusal names what exists, so the caller can correct it."""
    if requested is None:
        return []
    if not isinstance(requested, list) or not all(isinstance(name, str) for name in requested):
        raise ValueError('station tools must be a list of configured MCP server names')
    if EVERYTHING in requested:
        return [EVERYTHING]
    known = servers()
    unknown = sorted(set(requested) - set(known) - BASE)
    if unknown:
        raise ValueError(f'unknown station tools {unknown}; configured: {sorted(set(known) - BASE)}')
    return sorted(set(requested) - BASE)


def grants(granted: list[str], server: str) -> bool:
    return EVERYTHING in granted or server in granted


def covers(granted: list[str], requested: list[str]) -> bool:
    """Whether a station holding `granted` can pass `requested` on."""
    return EVERYTHING in granted or (EVERYTHING not in requested and set(requested) <= set(granted))


def directory(value) -> str:
    """An existing directory, as its real path: symlinks cannot move a station later."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError('station directory must be a path')
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError(f'station directory must be absolute or start with ~: {value!r}')
    if not path.is_dir():
        raise ValueError(f'station directory does not exist: {value!r}')
    return str(path.resolve())


def stationed(task: dict) -> bool:
    """A system-scoped Operator working outside the runtime, rather than maintaining it."""
    return (task.get('role') == 'operator' and task.get('place') == 'system' and task.get('branch') is None
            and Path(task.get('worktree', ROOT)).resolve() != ROOT.resolve())


def of(task: dict) -> dict:
    return {'directory': task['worktree'], 'tools': task.get('tools') or []}
