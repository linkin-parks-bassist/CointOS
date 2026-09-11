"""Sole owner of CointOS source-root and runtime-root discovery.

The source root resolves from the installed location of this module, so it
tracks the checkout wherever it lives. The runtime root defaults to the
current user's ``~/.CointOS`` and accepts an explicit absolute-path override
via the ``COINTOS_RUNTIME_ROOT`` environment variable; a relative or empty
override raises instead of falling back. Functions and plain data only:
no classes, no I/O beyond environment lookup.
"""

import os
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME_ROOT = Path.home() / ".CointOS"
RUNTIME_ROOT_ENV = "COINTOS_RUNTIME_ROOT"

_STATE_DIR = "state"
_LOGS_DIR = "logs"


def source_root():
    """Return the source root as an absolute Path.

    Resolved from the installed location of this module.
    """
    return SOURCE_ROOT


def runtime_root():
    """Return the runtime root as an absolute Path.

    Defaults to the current user's ``~/.CointOS``. When
    ``COINTOS_RUNTIME_ROOT`` is set, it must name an absolute path; a relative
    or empty value raises ``ValueError``. There is no silent fallback.
    """
    override = os.environ.get(RUNTIME_ROOT_ENV)
    if override is None:
        return DEFAULT_RUNTIME_ROOT
    if not override or not os.path.isabs(override):
        raise ValueError(
            f"{RUNTIME_ROOT_ENV} must be an absolute path, got {override!r}")
    return Path(override)


def state_root():
    """Return the runtime state root (``<runtime root>/state``)."""
    return runtime_root() / _STATE_DIR


def logs_root():
    """Return the runtime logs root (``<runtime root>/logs``)."""
    return runtime_root() / _LOGS_DIR
