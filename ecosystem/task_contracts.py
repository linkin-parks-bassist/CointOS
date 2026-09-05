"""Validation for bounded executable work and inherited child authority."""
from __future__ import annotations

import json
import os
from pathlib import Path


BUDGET_FIELDS = (
    "run_seconds",
    "task_seconds",
    "maximum_attempts",
    "maximum_output_bytes",
    "maximum_evidence_items",
    "maximum_children",
)
CONTRACT_FIELDS = {
    "objective",
    "scope",
    "authority_profile",
    "acceptance",
    "budget",
    "source_key",
    "parent_job_id",
    "stop_condition",
}


def _durable_copy(value: dict, label: str) -> dict:
    try:
        encoded = json.dumps(value, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} is not durable JSON") from error
    return json.loads(encoded)


def _nonempty_text(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"invalid {label}")
    return value


def validate_budget(raw: dict) -> dict:
    if type(raw) is not dict or set(raw) != set(BUDGET_FIELDS):
        raise ValueError("budget must contain exactly the required fields")
    for field in BUDGET_FIELDS:
        value = raw[field]
        minimum = 0 if field == "maximum_children" else 1
        if type(value) is not int or value < minimum:
            raise ValueError(f"invalid budget {field}")
    return _durable_copy(raw, "budget")


def _canonical_absolute_path(value: object, label: str) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"invalid {label}")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError(f"{label} must be absolute")
    canonical = str(path.resolve(strict=False))
    if value != canonical:
        raise ValueError(f"{label} must be canonical")
    return canonical


def _contained(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((path, root)) == root
    except ValueError:
        return False


def _validate_scope(raw: object) -> dict:
    if type(raw) is not dict or set(raw) != {"workspace", "read_paths", "write_paths"}:
        raise ValueError("invalid task scope")
    workspace = _canonical_absolute_path(raw["workspace"], "scope workspace")
    result = {"workspace": workspace}
    for field in ("read_paths", "write_paths"):
        values = raw[field]
        if type(values) is not list:
            raise ValueError(f"scope {field} must be a list")
        canonical = [_canonical_absolute_path(value, f"scope {field}") for value in values]
        if len(canonical) != len(set(canonical)):
            raise ValueError(f"scope {field} contains duplicates")
        if any(not _contained(path, workspace) for path in canonical):
            raise ValueError(f"scope {field} escapes workspace")
        result[field] = canonical
    return result


def validate_task_contract(raw: dict) -> dict:
    if type(raw) is not dict or set(raw) != CONTRACT_FIELDS:
        raise ValueError("task contract must contain exactly the required fields")
    objective = _nonempty_text(raw["objective"], "task objective")
    authority = _nonempty_text(raw["authority_profile"], "authority profile")
    source_key = _nonempty_text(raw["source_key"], "source key")
    stop_condition = _nonempty_text(raw["stop_condition"], "stop condition")
    parent_job_id = raw["parent_job_id"]
    if parent_job_id is not None:
        _nonempty_text(parent_job_id, "parent job identity")
    acceptance = raw["acceptance"]
    if (type(acceptance) is not list
            or any(type(item) is not dict or not item
                   or type(item.get("kind")) is not str or not item["kind"].strip()
                   for item in acceptance)):
        raise ValueError("acceptance must be a list of structured checks")
    result = {
        "objective": objective,
        "scope": _validate_scope(raw["scope"]),
        "authority_profile": authority,
        "acceptance": acceptance,
        "budget": validate_budget(raw["budget"]),
        "source_key": source_key,
        "parent_job_id": parent_job_id,
        "stop_condition": stop_condition,
    }
    return _durable_copy(result, "task contract")


def _paths_within(child_paths: list[str], parent_paths: list[str]) -> bool:
    return all(any(_contained(path, permitted) for permitted in parent_paths)
               for path in child_paths)


def narrow_contract(parent: dict, child: dict) -> dict:
    parent_source = parent.get("task_contract", parent)
    parent_contract = validate_task_contract(
        {field: parent_source[field] for field in CONTRACT_FIELDS}
    )
    child_contract = validate_task_contract(child)
    if child_contract["parent_job_id"] is None:
        raise ValueError("child contract lacks parent identity")
    if child_contract["scope"]["workspace"] != parent_contract["scope"]["workspace"]:
        raise ValueError("child changes workspace")
    for field in ("read_paths", "write_paths"):
        if not _paths_within(child_contract["scope"][field], parent_contract["scope"][field]):
            raise ValueError(f"child widens {field[:-6]} scope")
    if child_contract["authority_profile"] != parent_contract["authority_profile"]:
        raise ValueError("child widens or changes authority")
    remaining = validate_budget(parent.get("remaining_budget", parent_contract["budget"]))
    for field in BUDGET_FIELDS[:-1]:
        if child_contract["budget"][field] > remaining[field]:
            raise ValueError(f"child exceeds remaining shared {field}")
    needed_children = 1 + child_contract["budget"]["maximum_children"]
    if needed_children > remaining["maximum_children"]:
        raise ValueError("child exceeds remaining shared maximum_children")
    return child_contract
