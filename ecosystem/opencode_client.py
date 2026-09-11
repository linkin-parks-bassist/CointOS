"""Version-qualified OpenCode capability boundary.

The installed OpenCode output ceiling is qualified once per exact version
identity with a focused probe or an authoritative client fact, then stored in
the checked-in catalogue `config/opencode-capabilities.json`. The ceiling is
never inferred from a context ratio and never defaulted for an unknown
version: an unknown or changed version invalidates the qualification and
closes launch until it is requalified. The returned capability record uses
exactly the keys `ecosystem.opencode_capacity.effective_inference_capacity`
accepts as its client capability argument.
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
    """Resolve one exact OpenCode version to its qualified capability.

    `version_text` is the literal output of
    `/home/david/.opencode/bin/opencode --version` (a surrounding newline is
    tolerated, nothing else). Returns a plain capability dictionary, or raises
    ValueError naming the missing qualification; there is no default.
    """
    if not isinstance(version_text, str):
        raise ValueError("version text must be a string")
    version = version_text.strip()
    if not version:
        raise ValueError("version text must not be empty")
    versions = _validate_catalogue(catalogue)
    if version not in versions:
        raise ValueError(
            f"OpenCode version {version!r} has no qualification in the "
            "catalogue; there is no default capability and launch stays "
            "closed until requalified")
    ceiling = _validate_entry(version, versions[version])
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
