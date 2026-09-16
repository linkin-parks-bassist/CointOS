"""Observe OpenCode identity without making package updates an admission gate.

Known versions retain measured client ceilings.  An unknown version uses no
additional client ceiling: backend observations and configured output reserve
remain the authoritative bounds, so an ordinary package update cannot strand
otherwise valid local work.
"""

from __future__ import annotations

import json
from pathlib import Path

CAPABILITY_KEYS = ("version", "qualified", "maximum_output_tokens")
ENTRY_KEYS = ("maximum_output_tokens", "qualified_at", "evidence")


def _positive_integer(value, where):
    if type(value) is not int or value <= 0:
        raise ValueError(f"{where} must be a positive integer")
    return value


def _validate_entry(version, entry):
    if not isinstance(entry, dict):
        raise ValueError(
            f"catalogue entry for OpenCode {version!r} must be a dictionary")
    missing = [key for key in ENTRY_KEYS if key not in entry]
    if missing:
        raise ValueError(
            f"catalogue entry for OpenCode {version!r} is missing keys {missing}")
    unknown = sorted(set(entry) - set(ENTRY_KEYS))
    if unknown:
        raise ValueError(
            f"catalogue entry for OpenCode {version!r} has unknown keys {unknown}")
    ceiling = _positive_integer(
        entry["maximum_output_tokens"],
        f"catalogue entry for OpenCode {version!r} maximum_output_tokens")
    qualified_at = entry["qualified_at"]
    if not isinstance(qualified_at, str) or not qualified_at:
        raise ValueError(
            f"catalogue entry for OpenCode {version!r} qualified_at must be a "
            "non-empty string")
    evidence = entry["evidence"]
    if not isinstance(evidence, str) or not evidence:
        raise ValueError(
            f"catalogue entry for OpenCode {version!r} evidence must be a "
            "non-empty string")
    return ceiling


def _validate_catalogue(catalogue):
    if not isinstance(catalogue, dict):
        raise ValueError("catalogue must be a dictionary")
    missing = [key for key in ("versions",) if key not in catalogue]
    if missing:
        raise ValueError(f"catalogue is missing required keys {missing}")
    unknown = sorted(set(catalogue) - {"versions"})
    if unknown:
        raise ValueError(f"catalogue has unknown keys {unknown}")
    versions = catalogue["versions"]
    if not isinstance(versions, dict):
        raise ValueError("catalogue versions must be a dictionary")
    for version, entry in versions.items():
        if not isinstance(version, str) or not version:
            raise ValueError(
                f"catalogue version key {version!r} must be a non-empty string")
        _validate_entry(version, entry)
    return versions


def qualified_opencode_capability(version_text, catalogue):
    """Return observed client identity and any known measured output ceiling."""
    if not isinstance(version_text, str):
        raise ValueError("version text must be a string")
    version = version_text.strip()
    if not version:
        raise ValueError("version text must not be empty")
    versions = _validate_catalogue(catalogue)
    # An unknown client must not become a dispatch barrier.  A deliberately
    # huge ceiling means this layer imposes no additional cap; fresh backend
    # capacity and the configured output reserve still bound every request.
    ceiling = (_validate_entry(version, versions[version])
               if version in versions else (1 << 63) - 1)
    return {
        "version": version,
        "qualified": True,
        "maximum_output_tokens": ceiling,
    }


def _reject_duplicate_pairs(pairs):
    keys = [key for key, _ in pairs]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        raise ValueError(f"capability catalogue contains duplicate keys {duplicates}")
    return dict(pairs)


def load_capability_catalogue(path):
    """Read and strictly validate the checked-in qualification catalogue."""
    raw = Path(path).read_text(encoding="utf-8")
    try:
        catalogue = json.loads(raw, object_pairs_hook=_reject_duplicate_pairs)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"capability catalogue {path} is not valid JSON: {error}") from None
    _validate_catalogue(catalogue)
    return catalogue
