import json
import os
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path

from ecosystem import operator_session
from tests.test_operator_session import (
    load_state,
    scheduling_snapshot,
    session_request,
)


def _reap_leaked_child(pidfile: Path) -> None:
    if not pidfile.exists():
        return
    pid = int(pidfile.read_text(encoding="utf-8").strip())
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass


def test_run_command_child_requires_active_session_before_marker():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "state").mkdir()
        (root / "state" / "scheduling-policy.json").write_text(
            json.dumps(scheduling_snapshot()), encoding="utf-8")
        marker = root / "marker"
        state_path = root / "state" / "operator-sessions.json"
        child = (
            "import json, sys\n"
            f"document = json.load(open({str(state_path)!r}))\n"
            "if document['sessions']['opencode:one']['state'] != 'active':\n"
            "    sys.exit(7)\n"
            f"open({str(marker)!r}, 'w').write('done')\n"
            "sys.exit(3)\n"
        )
        code = operator_session.run_command(
            root, session_request(), [sys.executable, "-c", child])
        assert code == 3
        assert marker.read_text(encoding="utf-8") == "done"
        session = load_state(root)["sessions"]["opencode:one"]
        assert session["state"] == "release_requested"
        assert session["release_outcome"] == {
            "state": "run_finished", "returncode": 3}


def test_run_command_registration_failure_never_executes_child():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "state").mkdir()
        (root / "state" / "scheduling-policy.json").write_text(
            json.dumps(scheduling_snapshot()), encoding="utf-8")
        marker = root / "marker"
        pidfile = root / "child-pid"
        child = (
            "import os, time\n"
            f"open({str(pidfile)!r}, 'w').write(str(os.getpid()))\n"
            f"open({str(marker)!r}, 'w').write('ran')\n"
            "time.sleep(30)\n"
        )
        observed = {"marker": False}

        def failing_registrar(*_args, **_kwargs):
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                observed["marker"] = marker.exists() or observed["marker"]
                if observed["marker"]:
                    break
                time.sleep(0.05)
            raise RuntimeError("injected registration failure")

        original = operator_session.register_operator_process
        operator_session.register_operator_process = failing_registrar
        raised = None
        try:
            operator_session.run_command(
                root, session_request(), [sys.executable, "-c", child])
        except RuntimeError as error:
            raised = error
        else:
            raise AssertionError("registration failure did not propagate")
        finally:
            operator_session.register_operator_process = original
        try:
            assert not observed["marker"], "child executed before registration"
            assert not marker.exists()
            assert raised.args == ("injected registration failure",)
            failure = getattr(raised, "launch_failure", None)
            assert failure is not None
            assert failure["spawned"] is True
            assert type(failure["pid"]) is int and failure["pid"] > 0
            assert type(failure["start_ticks"]) is int
            assert type(failure["pgid"]) is int
            assert failure["cleanup"]["state"] == "reaped"
            assert failure["cleanup"]["process_group_alive"] is False
            session = load_state(root)["sessions"]["opencode:one"]
            assert session["state"] == "starting"
            assert session["process"] is None
        finally:
            _reap_leaked_child(pidfile)


def test_run_command_preserves_setup_error_when_cleanup_raises():
    from unittest import mock

    from ecosystem import executor

    registration_error = ValueError("injected registration failure")
    cleanup_error = OSError("injected cleanup failure")
    gate = {"pid": 4242, "start_ticks": 7, "pgid": 4242, "process": None}

    with tempfile.TemporaryDirectory() as temporary:
        with mock.patch.object(
                operator_session, "acquire_operator_session",
                return_value={
                    "state": "starting",
                    "session_id": "opencode:one",
                }), \
                mock.patch.object(
                    executor, "gated_child_launch", return_value=gate), \
                mock.patch.object(
                    operator_session, "register_operator_process",
                    side_effect=registration_error), \
                mock.patch.object(
                    executor, "gated_child_cleanup",
                    side_effect=cleanup_error):
            raised = None
            try:
                operator_session.run_command(
                    Path(temporary), session_request(), ["true"])
            except BaseException as error:
                raised = error
            else:
                raise AssertionError("registration failure did not propagate")
    assert raised is registration_error, (
        f"expected the original registration exception object, got "
        f"{type(raised).__name__}: {raised}")
    assert raised.__cause__ is cleanup_error, (
        f"expected __cause__ to be the cleanup exception object, "
        f"got {raised.__cause__!r}")
    failure = raised.launch_failure
    assert failure["spawned"] is True
    assert failure["pid"] == 4242
    assert failure["start_ticks"] == 7
    assert failure["pgid"] == 4242
    assert failure["cleanup"] == {
        "state": "reconciliation_required",
        "error_type": "OSError",
    }


def load_tests(_loader, _tests, _pattern):
    return unittest.TestSuite(
        unittest.FunctionTestCase(fn) for name, fn in globals().items()
        if name.startswith("test_") and callable(fn))
