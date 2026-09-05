import hashlib
import inspect
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ecosystem import operator_session


def scheduling_snapshot(user_driven: bool = True):
    bands = {
        "sole_survivor": 1000,
        "coin": 900,
        "small_health": 800,
        "large_health": 700,
        "default": 500,
    }
    if user_driven:
        bands["user_driven"] = 850
    values = {
        "version": 1,
        "priority_bands": bands,
        "authority_profiles": {
            "sole_survivor": "sole_survivor",
            "coin": "coin",
        },
        "execution_profiles": {
            "small_health": "small_health",
            "large_health": "large_health",
        },
        "role_priorities": {"default": 250},
        "aging_seconds_per_point": 60,
    }
    canonical = json.dumps(
        values, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return {
        "schema_version": 1,
        "values": values,
        "digest": hashlib.sha256(canonical).hexdigest(),
        "activated_at": "2026-09-05T00:00:00+00:00",
        "source_path": "config/scheduling.json",
    }


def root_with_snapshot(user_driven: bool = True) -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "state").mkdir()
    (root / "state" / "scheduling-policy.json").write_text(
        json.dumps(scheduling_snapshot(user_driven)), encoding="utf-8",
    )
    return root


def session_request(**changes) -> dict:
    request = {
        "session_id": "opencode:one",
        "owner_identity": "operator:opencode:one",
        "tool": "opencode",
        "model_id": "model-a",
        "request_id": "operator-request-one",
    }
    request.update(changes)
    return request


def observation(session_id: str, alive: bool = False) -> dict:
    return {
        "session_id": session_id,
        "pid": 100,
        "process_start_ticks": 200,
        "process_group_alive": alive,
    }


def coin_evidence(**changes) -> dict:
    evidence = {
        "kind": "coin_reserve",
        "required_bytes": 8 * 1024 ** 3,
        "incident_id": "pressure-20260905T000000Z",
    }
    evidence.update(changes)
    return evidence


def load_state(root: Path) -> dict:
    return json.loads(
        (root / "state" / "operator-sessions.json").read_text(encoding="utf-8"),
    )


def test_acquire_creates_starting_session_and_is_idempotent():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "state").mkdir()
        (root / "state" / "scheduling-policy.json").write_text(
            json.dumps(scheduling_snapshot()), encoding="utf-8")
        clock = lambda: 10.0
        session = operator_session.acquire_operator_session(
            root, session_request(), clock)
        assert session["state"] == "starting"
        assert session["process"] is None
        again = operator_session.acquire_operator_session(
            root, session_request(), clock)
        assert again == session
        same = load_state(root)["sessions"]
        assert set(same) == {"opencode:one"}


def test_acquire_rejects_duplicate_request_id_with_different_request():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "state").mkdir()
        (root / "state" / "scheduling-policy.json").write_text(
            json.dumps(scheduling_snapshot()), encoding="utf-8")
        clock = lambda: 10.0
        operator_session.acquire_operator_session(root, session_request(), clock)
        try:
            operator_session.acquire_operator_session(
                root,
                session_request(session_id="opencode:two"),
                clock,
            )
        except ValueError as error:
            assert "identity mismatch" in str(error)
        else:
            raise AssertionError("duplicate request identity was admitted")


def test_acquire_refuses_without_user_driven_band():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "state").mkdir()
        (root / "state" / "scheduling-policy.json").write_text(
            json.dumps(scheduling_snapshot(user_driven=False)), encoding="utf-8")
        clock = lambda: 10.0
        try:
            operator_session.acquire_operator_session(
                root, session_request(), clock)
        except ValueError as error:
            assert "user_driven" in str(error)
        else:
            raise AssertionError("session admitted without a user_driven band")
        assert not (root / "state" / "operator-sessions.json").exists()


def test_acquire_refuses_invalid_requests():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "state").mkdir()
        (root / "state" / "scheduling-policy.json").write_text(
            json.dumps(scheduling_snapshot()), encoding="utf-8")
        clock = lambda: 10.0
        for broken in (
            {},
            session_request(owner_identity="worker:one"),
            session_request(session_id=""),
            session_request(tool=""),
            session_request(model_id=""),
            session_request(request_id=""),
        ):
            try:
                operator_session.acquire_operator_session(root, broken, clock)
            except ValueError:
                pass
            else:
                raise AssertionError(f"invalid request admitted: {broken}")
        assert not (root / "state" / "operator-sessions.json").exists()


def test_register_process_moves_session_to_active():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "state").mkdir()
        (root / "state" / "scheduling-policy.json").write_text(
            json.dumps(scheduling_snapshot()), encoding="utf-8")
        clock = lambda: 10.0
        operator_session.acquire_operator_session(root, session_request(), clock)
        registered = operator_session.register_operator_process(
            root, "opencode:one", 100, 200, clock)
        assert registered["state"] == "active"
        assert registered["process"] == {"pid": 100, "process_start_ticks": 200}
        again = operator_session.register_operator_process(
            root, "opencode:one", 100, 200, clock)
        assert again == registered
        try:
            operator_session.register_operator_process(
                root, "opencode:one", 101, 200, clock)
        except ValueError:
            pass
        else:
            raise AssertionError("different process identity was accepted")


def test_release_records_outcome_and_is_idempotent():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "state").mkdir()
        (root / "state" / "scheduling-policy.json").write_text(
            json.dumps(scheduling_snapshot()), encoding="utf-8")
        clock = lambda: 10.0
        operator_session.acquire_operator_session(root, session_request(), clock)
        operator_session.register_operator_process(
            root, "opencode:one", 100, 200, clock)
        outcome = {"state": "run_finished", "returncode": 0}
        released = operator_session.release_operator_session(
            root, "opencode:one", outcome, clock)
        assert released["state"] == "release_requested"
        assert released["release_outcome"] == outcome
        again = operator_session.release_operator_session(
            root, "opencode:one", outcome, clock)
        assert again["state"] == "release_requested"
        try:
            operator_session.release_operator_session(
                root, "opencode:one",
                {"state": "run_finished", "returncode": 1}, clock)
        except ValueError as error:
            assert "mismatch" in str(error)
        else:
            raise AssertionError("different release outcome was accepted")


def test_observe_quiesces_released_session_once_dead():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "state").mkdir()
        (root / "state" / "scheduling-policy.json").write_text(
            json.dumps(scheduling_snapshot()), encoding="utf-8")
        clock = lambda: 10.0
        operator_session.acquire_operator_session(root, session_request(), clock)
        operator_session.register_operator_process(
            root, "opencode:one", 100, 200, clock)
        operator_session.release_operator_session(
            root, "opencode:one",
            {"state": "run_finished", "returncode": 0}, clock)
        operator_session.observe_operator_sessions(
            root, [observation("opencode:one", alive=True)], clock)
        assert load_state(root)["sessions"]["opencode:one"]["state"] \
            == "release_requested"
        operator_session.observe_operator_sessions(
            root, [observation("opencode:one", alive=False)], clock)
        session = load_state(root)["sessions"]["opencode:one"]
        assert session["state"] == "quiescent"


def test_observed_death_without_release_is_dead_unreconciled():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "state").mkdir()
        (root / "state" / "scheduling-policy.json").write_text(
            json.dumps(scheduling_snapshot()), encoding="utf-8")
        clock = lambda: 10.0
        operator_session.acquire_operator_session(root, session_request(), clock)
        operator_session.register_operator_process(
            root, "opencode:one", 100, 200, clock)
        operator_session.observe_operator_sessions(
            root, [observation("opencode:one", alive=False)], clock)
        session = load_state(root)["sessions"]["opencode:one"]
        assert session["state"] == "dead_unreconciled"
        try:
            operator_session.register_operator_process(
                root, "opencode:one", 100, 200, clock)
        except ValueError:
            pass
        else:
            raise AssertionError("dead session accepted re-registration")


def test_dead_unreconciled_session_needs_explicit_reconciliation():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "state").mkdir()
        (root / "state" / "scheduling-policy.json").write_text(
            json.dumps(scheduling_snapshot()), encoding="utf-8")
        clock = lambda: 10.0
        operator_session.acquire_operator_session(root, session_request(), clock)
        operator_session.register_operator_process(
            root, "opencode:one", 100, 200, clock)
        operator_session.observe_operator_sessions(
            root, [observation("opencode:one", alive=False)], clock)
        try:
            operator_session.reconcile_operator_session(
                root, "opencode:one", {"evidence_id": ""}, clock)
        except ValueError:
            pass
        else:
            raise AssertionError("empty evidence reconciled a dead session")
        reconciled = operator_session.reconcile_operator_session(
            root, "opencode:one", {"evidence_id": "sigterm-100"}, clock)
        assert reconciled["state"] == "quiescent"
        again = operator_session.reconcile_operator_session(
            root, "opencode:one", {"evidence_id": "sigterm-100"}, clock)
        assert again["state"] == "quiescent"
        try:
            operator_session.reconcile_operator_session(
                root, "opencode:one", {"evidence_id": "other"}, clock)
        except ValueError:
            pass
        else:
            raise AssertionError("conflicting evidence reconciled a dead session")


def test_active_session_owns_its_pinned_model():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "state").mkdir()
        (root / "state" / "scheduling-policy.json").write_text(
            json.dumps(scheduling_snapshot()), encoding="utf-8")
        clock = lambda: 10.0
        operator_session.acquire_operator_session(root, session_request(), clock)
        assert operator_session.operator_session_owns_model(
            root, "model-a") is None
        operator_session.register_operator_process(
            root, "opencode:one", 100, 200, clock)
        assert operator_session.operator_session_owns_model(
            root, "model-a") == "opencode:one"
        assert operator_session.operator_session_owns_model(
            root, "model-b") is None
        operator_session.release_operator_session(
            root, "opencode:one",
            {"state": "run_finished", "returncode": 0}, clock)
        assert operator_session.operator_session_owns_model(
            root, "model-a") is None


def test_null_model_pins_nothing():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "state").mkdir()
        (root / "state" / "scheduling-policy.json").write_text(
            json.dumps(scheduling_snapshot()), encoding="utf-8")
        clock = lambda: 10.0
        operator_session.acquire_operator_session(
            root, session_request(model_id=None), clock)
        operator_session.register_operator_process(
            root, "opencode:one", 100, 200, clock)
        assert operator_session.operator_session_owns_model(
            root, "model-a") is None


def test_preempt_requires_coin_reserve_evidence_and_releases_active_sessions():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "state").mkdir()
        (root / "state" / "scheduling-policy.json").write_text(
            json.dumps(scheduling_snapshot()), encoding="utf-8")
        clock = lambda: 10.0
        operator_session.acquire_operator_session(root, session_request(), clock)
        operator_session.register_operator_process(
            root, "opencode:one", 100, 200, clock)
        second = session_request(
            session_id="opencode:two", owner_identity="operator:opencode:two",
            model_id="model-b", request_id="operator-request-two")
        operator_session.acquire_operator_session(root, second, clock)
        for broken in (
            coin_evidence(kind="pressure"),
            coin_evidence(required_bytes=0),
            coin_evidence(incident_id=""),
            {},
        ):
            try:
                operator_session.preempt_operator_sessions(root, broken, clock)
            except ValueError:
                pass
            else:
                raise AssertionError(f"invalid evidence accepted: {broken}")
        assert load_state(root)["sessions"]["opencode:one"]["state"] == "active"
        preempted = operator_session.preempt_operator_sessions(
            root, coin_evidence(), clock)
        assert {item["session_id"] for item in preempted} == {
            "opencode:one"}
        session = load_state(root)["sessions"]["opencode:one"]
        assert session["state"] == "release_requested"
        assert session["release_outcome"] == {
            "state": "preempted", "returncode": None}
        assert operator_session.operator_session_owns_model(
            root, "model-a") is None


def test_preempt_is_idempotent_and_ignores_quiescent_sessions():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "state").mkdir()
        (root / "state" / "scheduling-policy.json").write_text(
            json.dumps(scheduling_snapshot()), encoding="utf-8")
        clock = lambda: 10.0
        operator_session.acquire_operator_session(root, session_request(), clock)
        operator_session.register_operator_process(
            root, "opencode:one", 100, 200, clock)
        operator_session.release_operator_session(
            root, "opencode:one",
            {"state": "run_finished", "returncode": 0}, clock)
        operator_session.observe_operator_sessions(
            root, [observation("opencode:one", alive=False)], clock)
        preempted = operator_session.preempt_operator_sessions(
            root, coin_evidence(), clock)
        assert preempted == []


def test_release_of_preempted_session_keeps_preempted_outcome():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "state").mkdir()
        (root / "state" / "scheduling-policy.json").write_text(
            json.dumps(scheduling_snapshot()), encoding="utf-8")
        clock = lambda: 10.0
        operator_session.acquire_operator_session(root, session_request(), clock)
        operator_session.register_operator_process(
            root, "opencode:one", 100, 200, clock)
        operator_session.preempt_operator_sessions(root, coin_evidence(), clock)
        try:
            operator_session.release_operator_session(
                root, "opencode:one",
                {"state": "run_finished", "returncode": 0}, clock)
        except ValueError:
            pass
        else:
            raise AssertionError("preempted session took a different outcome")


def test_cli_run_spawns_waits_and_releases():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "state").mkdir()
        (root / "state" / "scheduling-policy.json").write_text(
            json.dumps(scheduling_snapshot()), encoding="utf-8")
        exit_code = operator_session.main([
            "run", "--session-id", "opencode:two",
            "--owner", "operator:opencode:two", "--tool", "opencode",
            "--model", "model-a", "--root", str(root),
            "--", "true",
        ])
        assert exit_code == 0
        session = load_state(root)["sessions"]["opencode:two"]
        assert session["state"] == "release_requested"
        assert session["release_outcome"] == {
            "state": "run_finished", "returncode": 0}
        assert session["process"] is not None


def test_cli_run_refuses_non_fresh_session():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "state").mkdir()
        (root / "state" / "scheduling-policy.json").write_text(
            json.dumps(scheduling_snapshot()), encoding="utf-8")
        request = session_request(
            session_id="opencode:three",
            owner_identity="operator:opencode:three",
            request_id="opencode:three:opencode",
        )
        operator_session.acquire_operator_session(root, request, lambda: 1.0)
        operator_session.release_operator_session(
            root, "opencode:three",
            {"state": "run_finished", "returncode": 0}, lambda: 2.0)
        with unittest.TestCase().assertRaisesRegex(ValueError, "not fresh"):
            operator_session.main([
                "run", "--session-id", "opencode:three",
                "--owner", "operator:opencode:three", "--tool", "opencode",
                "--model", "model-a", "--root", str(root),
                "--", "true",
            ])
        assert load_state(root)["sessions"]["opencode:three"]["state"] \
            == "release_requested"


def test_wrapper_script_runs_tool_under_lease():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "state").mkdir()
        (root / "state" / "scheduling-policy.json").write_text(
            json.dumps(scheduling_snapshot()), encoding="utf-8")
        script = Path(__file__).resolve().parents[1] / "scripts" / \
            "cointos-opencode"
        result = subprocess.run(
            [str(script), "run", "--session-id", "opencode:four",
             "--owner", "operator:opencode:four", "--tool", "opencode",
             "--root", str(root),
             "--", sys.executable, "-c", "import sys; sys.exit(3)"],
            capture_output=True, text=True)
        assert result.returncode == 3
        session = load_state(root)["sessions"]["opencode:four"]
        assert session["state"] == "release_requested"
        assert session["release_outcome"] == {
            "state": "run_finished", "returncode": 3}


def load_tests(_loader, _tests, _pattern):
    functions = [
        value for name, value in globals().items()
        if name.startswith("test_") and inspect.isfunction(value)
    ]
    return unittest.TestSuite(unittest.FunctionTestCase(value) for value in functions)
