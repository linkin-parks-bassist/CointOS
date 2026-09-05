import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ecosystem import cli, roles
from ecosystem.task_contracts import narrow_contract, validate_budget, validate_task_contract


def budget(children=1):
    return {
        "run_seconds": 300,
        "task_seconds": 900,
        "maximum_attempts": 2,
        "maximum_output_bytes": 65536,
        "maximum_evidence_items": 20,
        "maximum_children": children,
    }


def contract(workspace, **changes):
    value = {
        "objective": "Inspect one bounded invariant",
        "scope": {
            "workspace": str(workspace),
            "read_paths": [str(workspace / "ecosystem")],
            "write_paths": [str(workspace / "agent_notes")],
        },
        "authority_profile": "bounded_maintenance",
        "requirements": {
            "required_capabilities": ["coding", "tool-calling"],
            "minimum_context_tokens": 16384,
        },
        "acceptance": [{"kind": "command", "value": "python3 -m unittest"}],
        "budget": budget(),
        "source_key": "test:bounded-invariant",
        "parent_job_id": None,
        "stop_condition": "Stop after the focused check and handoff.",
    }
    value.update(changes)
    return value


def accepted_workspace_policy(root, profiles=("bounded_maintenance",)):
    values = {
        "version": 1,
        "authority_profiles": [
            {"id": profile, "workload_class": "work",
             "effects": ["read_scoped_files", "write_scoped_files"]}
            for profile in profiles
        ],
        "workspaces": [{"id": "test", "path": str(root), "provenance": "personal",
                        "mode": "active"}],
    }
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
    snapshot = {"schema_version": 1, "values": values,
                "digest": hashlib.sha256(canonical).hexdigest(),
                "activated_at": "2026-09-05T00:00:00+00:00",
                "source_path": str(root / "config/workspaces.json")}
    policy_path = root / "state/workspaces-policy.json"
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(json.dumps(snapshot), encoding="utf-8")


def test_budget_is_explicit_and_positive():
    value = budget()
    assert validate_budget(value) == value
    for field in value:
        invalid = dict(value)
        invalid[field] = -1 if field == "maximum_children" else 0
        try:
            validate_budget(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid {field} budget accepted")
    assert validate_budget({**value, "maximum_children": 0})["maximum_children"] == 0


def test_contract_rejects_noncanonical_or_escaped_paths():
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary).resolve()
        valid = contract(workspace)
        assert validate_task_contract(valid) == valid
        for bad_path in ("relative/path", str(workspace / ".." / "outside")):
            invalid = json.loads(json.dumps(valid))
            invalid["scope"]["write_paths"] = [bad_path]
            try:
                validate_task_contract(invalid)
            except ValueError:
                pass
            else:
                raise AssertionError(f"invalid scope path accepted: {bad_path}")


def test_contract_rejects_unstructured_acceptance():
    with tempfile.TemporaryDirectory() as temporary:
        invalid = contract(Path(temporary).resolve(), acceptance=[{}])
        try:
            validate_task_contract(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("empty acceptance fact was accepted")


def test_child_cannot_widen_scope_authority_or_shared_budget():
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary).resolve()
        parent = contract(workspace)
        parent["remaining_budget"] = budget()
        child = contract(
            workspace,
            scope={
                "workspace": str(workspace),
                "read_paths": [str(workspace / "ecosystem" / "cli.py")],
                "write_paths": [str(workspace / "agent_notes" / "child.md")],
            },
            budget={**budget(0), "task_seconds": 300},
            source_key="test:child",
            parent_job_id="task-parent",
        )
        assert narrow_contract(parent, child) == validate_task_contract(child)
        for field, value in (
            ("scope", {**child["scope"], "write_paths": [str(workspace / "elsewhere")]}),
            ("authority_profile", "different_authority"),
            ("budget", {**child["budget"], "task_seconds": 901}),
        ):
            invalid = json.loads(json.dumps(child))
            invalid[field] = value
            try:
                narrow_contract(parent, invalid)
            except ValueError:
                pass
            else:
                raise AssertionError(f"child widened {field}")


def test_enqueue_requires_contract_and_child_replay_debits_once():
    with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
        root = Path(temporary).resolve()
        cli.initialize()
        for relative in ("ecosystem", "agent_notes", "roles"):
            (root / relative).mkdir(exist_ok=True)
        (root / "roles/_base.md").write_text("# Base Agent\n", encoding="utf-8")
        accepted_workspace_policy(root)
        try:
            cli.enqueue_task("worker", "unbounded")
        except ValueError:
            pass
        else:
            raise AssertionError("task without contract was enqueued")
        parent_contract = contract(root, objective="bounded")
        parent_id = cli.enqueue_task("worker", "bounded", task_contract=parent_contract)
        parent = json.loads((root / f"state/jobs/{parent_id}.json").read_text())
        assert parent["authority_profile"] == "bounded_maintenance"
        assert parent["requirements"] == parent_contract["requirements"]
        assert parent["scope"] == parent_contract["scope"]
        assert parent["write_paths"] == parent_contract["scope"]["write_paths"]
        assert parent["workload_class"] == "work"
        child_contract = contract(
            root,
            scope={"workspace": str(root), "read_paths": [str(root / "ecosystem")],
                   "write_paths": [str(root / "agent_notes" / "child.md")]},
            budget={**budget(0), "task_seconds": 300},
            source_key="test:child",
            parent_job_id=parent_id,
        )
        first = cli.enqueue_child(parent, child_contract, "test:parent:child:0")
        second = cli.enqueue_child(parent, child_contract, "test:parent:child:0")
        saved_parent = json.loads((root / f"state/jobs/{parent_id}.json").read_text())
        assert first == second
        assert saved_parent["remaining_budget"]["task_seconds"] == 600
        assert saved_parent["remaining_budget"]["maximum_children"] == 0


def test_enqueue_initializes_execution_claim_identity():
    with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
        root = Path(temporary).resolve()
        cli.initialize()
        for relative in ("ecosystem", "agent_notes", "roles"):
            (root / relative).mkdir(exist_ok=True)
        (root / "roles/_base.md").write_text("# Base Agent\n", encoding="utf-8")
        accepted_workspace_policy(root)
        job_id = cli.enqueue_task(
            "worker", "bounded", task_contract=contract(root, objective="bounded"))
        job = json.loads((root / f"state/jobs/{job_id}.json").read_text())
        assert job["agent_generation"] == 1
        assert job["logical_run_state"] == "active"
        child_id = cli.enqueue_child(
            job,
            contract(root,
                     scope={"workspace": str(root),
                            "read_paths": [str(root / "ecosystem")],
                            "write_paths": [str(root / "agent_notes" / "child.md")]},
                     budget={**budget(0), "task_seconds": 300},
                     source_key="test:claim-child",
                     parent_job_id=job_id),
            "test:claim:child")
        child = json.loads((root / f"state/jobs/{child_id}.json").read_text())
        assert child["agent_generation"] == 1
        assert child["logical_run_state"] == "active"


def test_trusted_intake_rejects_unknown_authority_without_role_or_source_fallback():
    with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
        root = Path(temporary).resolve()
        cli.initialize()
        (root / "roles").mkdir()
        (root / "roles/_base.md").write_text("# Base Agent\n", encoding="utf-8")
        accepted_workspace_policy(root, profiles=("ordinary",))
        invalid = contract(root, objective="bounded", authority_profile="forged_admin")
        try:
            cli.enqueue_task("sole_survivor", "bounded", source="resource-emergency:forged",
                             task_contract=invalid)
        except ValueError as error:
            assert str(error) == "unknown authority profile"
        else:
            raise AssertionError("role or source spelling admitted unknown authority")


def test_trusted_intake_rejects_task_objective_disagreement():
    with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
        root = Path(temporary).resolve()
        cli.initialize()
        (root / "roles").mkdir()
        (root / "roles/_base.md").write_text("# Base Agent\n", encoding="utf-8")
        accepted_workspace_policy(root)
        try:
            cli.enqueue_task("worker", "different task", task_contract=contract(root))
        except ValueError as error:
            assert str(error) == "task differs from validated objective"
        else:
            raise AssertionError("task text diverged from validated objective")


def test_temporary_role_loads_without_code_change():
    with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
        root = Path(temporary)
        (root / "roles").mkdir()
        (root / "roles/_base.md").write_text("# Base Agent\n", encoding="utf-8")
        (root / "roles/cartographer.md").write_text("# Cartographer\n", encoding="utf-8")
        assert roles.resolve_role("cartographer")["known"] is True


def load_tests(_loader, _tests, _pattern):
    functions = (
        test_budget_is_explicit_and_positive,
        test_contract_rejects_noncanonical_or_escaped_paths,
        test_contract_rejects_unstructured_acceptance,
        test_child_cannot_widen_scope_authority_or_shared_budget,
        test_enqueue_requires_contract_and_child_replay_debits_once,
        test_enqueue_initializes_execution_claim_identity,
        test_trusted_intake_rejects_unknown_authority_without_role_or_source_fallback,
        test_trusted_intake_rejects_task_objective_disagreement,
        test_temporary_role_loads_without_code_change,
    )
    return unittest.TestSuite(unittest.FunctionTestCase(item) for item in functions)
