"""Strict parsing and transactional adoption for configuration families."""

import hashlib
import json
import math
from pathlib import Path
from typing import Callable

from survival.json_codec import decode_json_object


SNAPSHOT_FIELDS = {
    "schema_version", "values", "digest", "activated_at", "source_path",
}


def _reject_nonfinite(value):
    if type(value) is float and not math.isfinite(value):
        raise ValueError("nonfinite policy value")
    if type(value) is dict:
        for member in value.values():
            _reject_nonfinite(member)
    elif type(value) is list:
        for member in value:
            _reject_nonfinite(member)


def load_json_policy(path: Path, validate: Callable) -> dict:
    """Decode and validate one complete JSON policy family."""
    try:
        values = decode_json_object(Path(path).read_bytes(), "policy")
    except OSError as error:
        raise ValueError(f"cannot read policy {path}") from error
    _reject_nonfinite(values)
    validate(values)
    return values


def _accepted_snapshot(active: dict, validate: Callable) -> bool:
    valid_shape = (
        type(active) is dict
        and set(active) == SNAPSHOT_FIELDS
        and type(active["schema_version"]) is int
        and active["schema_version"] == 1
        and type(active["values"]) is dict
        and type(active["digest"]) is str
        and len(active["digest"]) == 64
        and all(character in "0123456789abcdef" for character in active["digest"])
        and type(active["activated_at"]) is str
        and bool(active["activated_at"])
        and type(active["source_path"]) is str
        and bool(active["source_path"])
    )
    if not valid_shape:
        return False
    try:
        canonical = json.dumps(
            active["values"], sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        values = json.loads(canonical)
        validate(values)
    except (TypeError, ValueError):
        return False
    return hashlib.sha256(canonical).hexdigest() == active["digest"]


def adopt_policy(
    active: dict,
    proposed: dict,
    validate: Callable,
    clock: dict,
) -> tuple[dict, str | None]:
    """Return a complete replacement snapshot, or the unchanged accepted one."""
    if not _accepted_snapshot(active, validate):
        return active, "no accepted policy snapshot"
    try:
        canonical = json.dumps(
            proposed, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        values = json.loads(canonical)
    except (TypeError, ValueError) as error:
        return active, f"policy publication failed: {error}"
    try:
        validate(values)
    except ValueError as error:
        return active, str(error)
    try:
        canonical = json.dumps(
            values, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        activated_at = clock["utc"]
        if type(activated_at) is not str or not activated_at:
            raise ValueError("invalid policy activation time")
        snapshot = {
            "schema_version": 1,
            "values": values,
            "digest": hashlib.sha256(canonical).hexdigest(),
            "activated_at": activated_at,
            "source_path": active["source_path"],
        }
        json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (KeyError, TypeError, ValueError) as error:
        return active, f"policy publication failed: {error}"
    return snapshot, None
