import os
import sys
import tempfile
import unittest
from pathlib import Path

from ecosystem.executor import (
    gated_child_cleanup,
    gated_child_launch,
    gated_child_release,
    gated_child_wait,
)


def _parent_fds() -> set:
    return {int(name) for name in os.listdir("/proc/self/fd")}


def _marker_child(marker: Path) -> list:
    return [
        sys.executable,
        "-c",
        "import pathlib, sys; pathlib.Path(sys.argv[1]).write_text('ran'); sys.exit(7)",
        str(marker),
    ]


def _expect_error(exc_type, fn):
    try:
        fn()
    except exc_type as raised:
        return raised
    raise AssertionError(f"{exc_type.__name__} not raised")


def test_none_config_fd_blocks_until_release_and_reaps_with_chosen_code():
    with tempfile.TemporaryDirectory(prefix="operator-gate-none-") as temporary:
        marker = Path(temporary) / "marker-none"
        record = None
        before = _parent_fds()
        try:
            record = gated_child_launch(None, _marker_child(marker), dict(os.environ))
            assert record["state"] == "blocked"
            assert record["config_fd"] == -1
            assert not marker.exists()
            gated_child_release(record)
            assert record["state"] == "gate_released"
            outcome = gated_child_wait(record, timeout=5.0)
            assert outcome["state"] == "reaped"
            assert outcome["returncode"] == 7
            assert marker.exists()
            cleanup = gated_child_cleanup(record, timeout=5.0)
        finally:
            if record is not None:
                gated_child_cleanup(record, timeout=2.0)
    assert cleanup["state"] == "reaped"
    assert cleanup["returncode"] == 7
    assert cleanup["process_group_alive"] is False
    assert _parent_fds() == before


def test_none_config_fd_preserves_injected_pre_spawn_failure():
    with tempfile.TemporaryDirectory(prefix="operator-gate-injected-") as temporary:
        marker = Path(temporary) / "marker-never"
        before = _parent_fds()

        def failing_popen(*_args, **_kwargs):
            raise OSError("injected pre-spawn failure")

        raised = _expect_error(
            OSError,
            lambda: gated_child_launch(
                None, _marker_child(marker), dict(os.environ),
                popen=failing_popen,
            ),
        )
        assert "injected pre-spawn failure" in str(raised)
        assert getattr(raised, "launch_failure", None) == {"spawned": False}
        assert not marker.exists()
        assert _parent_fds() == before


def test_none_config_fd_cleanup_without_release_reaps_blocked_wrapper():
    with tempfile.TemporaryDirectory(prefix="operator-gate-unreleased-") as temporary:
        marker = Path(temporary) / "marker-unreleased"
        record = None
        before = _parent_fds()
        try:
            record = gated_child_launch(None, _marker_child(marker), dict(os.environ))
            assert record["config_fd"] == -1
            assert not marker.exists()
            outcome = gated_child_cleanup(record, timeout=5.0)
        finally:
            if record is not None:
                gated_child_cleanup(record, timeout=2.0)
        assert Path(temporary).is_dir()
        assert not marker.exists()
        assert outcome["state"] == "reaped"
        assert outcome["process_group_alive"] is False
        assert _parent_fds() == before


def test_invalid_config_fd_values_are_still_rejected():
    with tempfile.TemporaryDirectory(prefix="operator-gate-invalid-") as temporary:
        marker = Path(temporary) / "marker-invalid"
        for invalid in (-1, -3, True, False, "0", 0.5, [0], b"0"):
            try:
                gated_child_launch(invalid, _marker_child(marker), dict(os.environ))
            except ValueError:
                pass
            else:
                raise AssertionError(f"ValueError not raised for {invalid!r}")
        assert Path(temporary).is_dir()
        assert not marker.exists()


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
