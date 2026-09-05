import json
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
        "acceptance": [{"kind": "command", "value": "python3 -m unittest"}],
        "budget": budget(),
        "source_key": "test:bounded-invariant",
        "parent_job_id": None,
        "stop_condition": "Stop after the focused check and handoff.",
    }
    value.update(changes)
    return value


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
        try:
            cli.enqueue_task("worker", "unbounded")
        except ValueError:
            pass
        else:
            raise AssertionError("task without contract was enqueued")
        parent_contract = contract(root)
        parent_id = cli.enqueue_task("worker", "bounded", task_contract=parent_contract)
        parent = json.loads((root / f"state/jobs/{parent_id}.json").read_text())
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
        test_temporary_role_loads_without_code_change,
    )
    return unittest.TestSuite(unittest.FunctionTestCase(item) for item in functions)
