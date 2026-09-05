import configparser
import tempfile
from pathlib import Path
import unittest

from ecosystem import workload_control


def worker_request(**changes):
    request = {
        "workload_class": "work",
        "model_id": "model-a",
        "context_tokens": 32768,
        "max_output_tokens": 2048,
        "deadline_monotonic": 300.0,
        "owner_identity": "codex:one",
        "job_id": "task-one",
        "agent_generation": 1,
        "caller_handle": "codex-call:one",
        "request_id": "request-one",
        "stop_method": "process_group",
    }
    request.update(changes)
    return request


def test_drain_closes_acquisition_before_snapshot():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        clock = lambda: 10.0
        workload_control.begin_drain(root, {"owner_identity": "smoke:one"}, clock)
        result = workload_control.acquire_worker(root, worker_request(), clock)
        assert result["state"] == "deferred"
        assert "drain" in result["reasons"]


def test_gate_cannot_clear_pressure_or_lifecycle_pause():
    reasons = workload_control.admission_reasons(
        {"mode": "pressure"}, {"paused": True}, {"mode": "open"})
    assert reasons == ["resource:pressure", "lifecycle:paused"]


def test_starting_lease_blocks_smoke_and_inference_until_pid_registration():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        clock = lambda: 10.0
        lease = workload_control.acquire_worker(root, worker_request(), clock)
        assert lease["state"] == "starting"
        drain = workload_control.begin_drain(root, {"owner_identity": "smoke:one"}, clock)
        assert drain["active_leases"][0]["lease_id"] == lease["lease_id"]
        smoke = workload_control.enter_smoke(
            root, {"owner_identity": "smoke:one"}, clock, [])
        assert smoke["state"] == "deferred"
        assert any("starting" in reason for reason in smoke["reasons"])

        registered = workload_control.register_process(
            root, lease["lease_id"], 100, 200, clock)
        assert registered["state"] == "active"


def test_pid_reuse_is_not_completion():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        clock = lambda: 10.0
        lease = workload_control.acquire_worker(root, worker_request(), clock)
        workload_control.register_process(root, lease["lease_id"], 100, 200, clock)
        workload_control.begin_drain(root, {"owner_identity": "smoke:one"}, clock)
        observed = workload_control.observe_workers(root, [{
            "lease_id": lease["lease_id"],
            "pid": 100,
            "process_start_ticks": 201,
            "process_group_alive": False,
            "backend_request_active": False,
            "inference_lease_active": False,
            "checkpoint_observed": True,
        }], clock)
        assert observed["leases"][lease["lease_id"]]["state"] == "dead_unreconciled"
        smoke = workload_control.enter_smoke(
            root, {"owner_identity": "smoke:one"}, clock, [])
        assert smoke["state"] == "deferred"


def test_checkpoint_without_process_and_request_exit_blocks_smoke():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        clock = lambda: 10.0
        lease = workload_control.acquire_worker(root, worker_request(), clock)
        workload_control.register_process(root, lease["lease_id"], 100, 200, clock)
        workload_control.begin_drain(root, {"owner_identity": "smoke:one"}, clock)
        observations = [{
            "lease_id": lease["lease_id"],
            "pid": 100,
            "process_start_ticks": 200,
            "process_group_alive": True,
            "backend_request_active": True,
            "inference_lease_active": True,
            "checkpoint_observed": True,
        }]
        smoke = workload_control.enter_smoke(
            root, {"owner_identity": "smoke:one"}, clock, observations)
        assert smoke["state"] == "deferred"
        assert any("process_group" in reason for reason in smoke["reasons"])
        assert any("backend_request" in reason for reason in smoke["reasons"])
        assert any("inference_lease" in reason for reason in smoke["reasons"])


def test_hosted_writer_blocks_covered_smoke():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        clock = lambda: 10.0
        lease = workload_control.acquire_worker(root, worker_request(
            caller_handle="hosted:writer-one",
            stop_method="hosted",
            write_paths=["ecosystem/workload_control.py"],
        ), clock)
        owner = {"owner_identity": "smoke:one", "covered_paths": ["ecosystem"]}
        workload_control.begin_drain(root, owner, clock)
        smoke = workload_control.enter_smoke(root, owner, clock, [{
            "lease_id": lease["lease_id"],
            "caller_handle": "hosted:writer-one",
            "writer_active": True,
            "write_paths": ["ecosystem/workload_control.py"],
        }])
        assert smoke["state"] == "deferred"

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        clock = lambda: 10.0
        owner = {"owner_identity": "smoke:one", "covered_paths": ["ecosystem"]}
        lease = workload_control.acquire_worker(root, worker_request(
            caller_handle="hosted:writer-one",
            stop_method="hosted",
            write_paths=["ecosystem/workload_control.py"],
        ), clock)
        workload_control.observe_workers(root, [{
            "lease_id": lease["lease_id"],
            "caller_handle": "hosted:writer-one",
            "writer_active": True,
            "write_paths": ["ecosystem/workload_control.py"],
        }], clock)
        workload_control.begin_drain(root, owner, clock)
        smoke = workload_control.enter_smoke(root, owner, clock, [])
        assert smoke["state"] == "deferred"
        assert any("hosted_writer" in reason for reason in smoke["reasons"])

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        clock = lambda: 10.0
        owner = {"owner_identity": "smoke:one", "covered_paths": ["ecosystem"]}
        lease = workload_control.acquire_worker(root, worker_request(
            caller_handle="hosted:writer-one",
            stop_method="hosted",
            write_paths=["ecosystem/workload_control.py"],
        ), clock)
        workload_control.begin_drain(root, owner, clock)
        smoke = workload_control.enter_smoke(root, owner, clock, [{
            "lease_id": lease["lease_id"],
            "caller_handle": "hosted:writer-one",
            "write_paths": ["ecosystem/workload_control.py"],
        }])
        assert smoke["state"] == "deferred"


def test_failed_smoke_does_not_clear_pressure():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        clock = lambda: 10.0
        owner = {"owner_identity": "smoke:one"}
        workload_control.begin_drain(root, owner, clock)
        entered = workload_control.enter_smoke(root, owner, clock, [])
        assert entered["mode"] == "smoke"
        ended = workload_control.end_smoke(
            root, owner, {"state": "failed", "reason": "probe failed"}, clock)
        assert ended["mode"] == "draining"
        reasons = workload_control.admission_reasons(
            {"mode": "pressure"}, {"paused": False}, ended)
        assert reasons == ["resource:pressure", "work:draining"]


def test_release_and_end_smoke_are_idempotent_but_identity_mismatch_fails():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        clock = lambda: 10.0
        lease = workload_control.acquire_worker(root, worker_request(), clock)
        outcome = {"state": "completed"}
        first = workload_control.release_worker(root, lease["lease_id"], outcome, clock)
        second = workload_control.release_worker(root, lease["lease_id"], outcome, clock)
        assert first == second
        with unittest.TestCase().assertRaisesRegex(ValueError, "outcome mismatch"):
            workload_control.release_worker(
                root, lease["lease_id"], {"state": "failed"}, clock)

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        clock = lambda: 10.0
        owner = {"owner_identity": "smoke:one"}
        workload_control.begin_drain(root, owner, clock)
        workload_control.enter_smoke(root, owner, clock, [])
        smoke_outcome = {"state": "passed"}
        first_end = workload_control.end_smoke(root, owner, smoke_outcome, clock)
        second_end = workload_control.end_smoke(root, owner, smoke_outcome, clock)
        assert first_end == second_end
        with unittest.TestCase().assertRaisesRegex(ValueError, "owner mismatch"):
            workload_control.end_smoke(
                root, {"owner_identity": "smoke:two"}, smoke_outcome, clock)


def test_workload_timing_policy_exposes_action_deadlines():
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(Path("config/time.cfg"), encoding="utf-8")
    assert parser.getfloat("workload", "maximum_run_seconds") == 300
    assert parser.getfloat("workload", "wrapup_seconds") == 30
    assert parser.getfloat("workload", "termination_grace_seconds") == 15


def load_tests(_loader, _tests, _pattern):
    functions = (
        test_drain_closes_acquisition_before_snapshot,
        test_gate_cannot_clear_pressure_or_lifecycle_pause,
        test_starting_lease_blocks_smoke_and_inference_until_pid_registration,
        test_pid_reuse_is_not_completion,
        test_checkpoint_without_process_and_request_exit_blocks_smoke,
        test_hosted_writer_blocks_covered_smoke,
        test_failed_smoke_does_not_clear_pressure,
        test_release_and_end_smoke_are_idempotent_but_identity_mismatch_fails,
        test_workload_timing_policy_exposes_action_deadlines,
    )
    return unittest.TestSuite(unittest.FunctionTestCase(item) for item in functions)
