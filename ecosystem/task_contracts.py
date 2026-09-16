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
    "requirements",
    "acceptance",
    "budget",
    "source_key",
    "parent_job_id",
    "stop_condition",
}
REQUIREMENT_FIELDS = {"required_capabilities", "minimum_context_tokens"}


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
        if value is None:
            continue
        minimum = 0 if field == "maximum_children" else 1
        if type(value) is not int or value < minimum:
            raise ValueError(f"invalid budget {field}")
    return _durable_copy(raw, "budget")


def validate_requirements(raw: dict) -> dict:
    if type(raw) is not dict or set(raw) != REQUIREMENT_FIELDS:
        raise ValueError("model requirements must contain exactly the required fields")
    capabilities = raw["required_capabilities"]
    if (type(capabilities) is not list or not capabilities
            or any(type(value) is not str or not value.strip() for value in capabilities)
            or len(capabilities) != len(set(capabilities))):
        raise ValueError("invalid required model capabilities")
    minimum = raw["minimum_context_tokens"]
    if type(minimum) is not int or minimum <= 0:
        raise ValueError("invalid minimum model context")
    return _durable_copy(raw, "model requirements")


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


def validate_scope(raw: object) -> dict:
    """Canonical scope contract: absolute workspace, contained read/write roots."""
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
        "scope": validate_scope(raw["scope"]),
        "authority_profile": authority,
        "requirements": validate_requirements(raw["requirements"]),
        "acceptance": acceptance,
        "budget": validate_budget(raw["budget"]),
        "source_key": source_key,
        "parent_job_id": parent_job_id,
        "stop_condition": stop_condition,
    }
    return _durable_copy(result, "task contract")


def validate_workspace_policy(values: dict) -> dict:
    if type(values) is not dict or set(values) != {"version", "authority_profiles", "workspaces"}:
        raise ValueError("invalid workspace authority policy")
    if values["version"] != 1:
        raise ValueError("invalid workspace authority policy version")
    profiles = values["authority_profiles"]
    workspaces = values["workspaces"]
    if type(profiles) is not list or type(workspaces) is not list:
        raise ValueError("invalid workspace authority policy")
    profile_ids = []
    for profile in profiles:
        if type(profile) is not dict or set(profile) != {"id", "effects", "workload_class"}:
            raise ValueError("invalid authority profile")
        profile_ids.append(_nonempty_text(profile["id"], "authority profile identity"))
        if profile["workload_class"] not in {"front", "repair", "work", "monitor"}:
            raise ValueError("invalid authority workload class")
        effects = profile["effects"]
        if (type(effects) is not list
                or any(type(effect) is not str or not effect for effect in effects)
                or len(effects) != len(set(effects))):
            raise ValueError("invalid authority profile effects")
    if len(profile_ids) != len(set(profile_ids)):
        raise ValueError("duplicate authority profile")
    workspace_paths = []
    for workspace in workspaces:
        if type(workspace) is not dict:
            raise ValueError("invalid workspace policy entry")
        for field in ("id", "path", "provenance", "mode"):
            _nonempty_text(workspace.get(field), f"workspace {field}")
        workspace_paths.append(_canonical_absolute_path(workspace["path"], "workspace path"))
    if len(workspace_paths) != len(set(workspace_paths)):
        raise ValueError("duplicate workspace path")
    return _durable_copy(values, "workspace authority policy")


def accepted_workspace_policy(root: Path) -> dict:
    from survival.configuration import adopt_policy
    from survival.json_codec import decode_json_object

    root = Path(root).resolve()
    path = root / "state/workspaces-policy.json"
    try:
        snapshot = decode_json_object(path.read_bytes(), "workspace authority snapshot")
        activated_at = snapshot["activated_at"]
        values = snapshot["values"]
    except (OSError, KeyError, TypeError, ValueError) as error:
        raise ValueError("no accepted workspace authority policy") from error
    accepted, error = adopt_policy(
        snapshot, values, validate_workspace_policy, {"utc": activated_at},
    )
    source = snapshot.get("source_path")
    source_path = Path(source) if type(source) is str else None
    if source_path is not None and not source_path.is_absolute():
        source_path = root / source_path
    expected_source = (root / "config/workspaces.json").resolve(strict=False)
    if (error is not None or accepted != snapshot or source_path is None
            or source_path.resolve(strict=False) != expected_source):
        raise ValueError("invalid accepted workspace authority policy")
    return accepted["values"]


def _resolved_authority(contract: dict, root: Path) -> tuple[dict, dict]:
    validated = validate_task_contract(contract)
    policy = accepted_workspace_policy(root)
    profile = next((item for item in policy["authority_profiles"]
                    if item["id"] == validated["authority_profile"]), None)
    if profile is None:
        raise ValueError("unknown authority profile")
    workspace = next((item for item in policy["workspaces"]
                      if item["path"] == validated["scope"]["workspace"]), None)
    if workspace is None or workspace["mode"] not in {"active", "immutable-reference"}:
        raise ValueError("workspace is not accepted for task execution")
    effects = set(profile["effects"])
    if validated["scope"]["read_paths"] and "read_scoped_files" not in effects:
        raise ValueError("authority profile does not permit scoped reads")
    if validated["scope"]["write_paths"] and not (
            {"write_scoped_files", "write_verdict"} & effects):
        raise ValueError("authority profile does not permit scoped writes")
    if workspace["mode"] == "immutable-reference" and validated["scope"]["write_paths"]:
        raise ValueError("immutable workspace cannot be writable")
    return validated, profile


def validate_task_authority(contract: dict, root: Path) -> dict:
    return _resolved_authority(contract, root)[0]


def resolve_task_intake(contract: dict, root: Path) -> dict:
    validated, profile = _resolved_authority(contract, root)
    return {
        "task_contract": validated,
        "authority_profile": validated["authority_profile"],
        "requirements": dict(validated["requirements"]),
        "scope": dict(validated["scope"]),
        "write_paths": list(validated["scope"]["write_paths"]),
        "workload_class": profile["workload_class"],
    }


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
