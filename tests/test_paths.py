import os
import unittest
from pathlib import Path
from unittest import mock

from ecosystem import paths

DEFAULT_ROOT = Path("/home/david/.CointOS")
OVERRIDE_ROOT = Path("/srv/cointos-runtime")
RELATIVE_OVERRIDE = "relative/cointos"


def _env(value):
    env = mock.patch.dict(os.environ)
    env.start()
    if value is None:
        os.environ.pop(paths.RUNTIME_ROOT_ENV, None)
    else:
        os.environ[paths.RUNTIME_ROOT_ENV] = value
    return env


def test_source_root_resolves_from_module_location():
    root = paths.source_root()
    assert root == Path(paths.__file__).resolve().parents[1]
    assert root.is_absolute()
    assert (root / "ecosystem" / "paths.py").resolve() == Path(
        paths.__file__).resolve()


def test_runtime_root_defaults_to_cointos_home():
    env = _env(None)
    try:
        assert paths.runtime_root() == DEFAULT_ROOT
    finally:
        env.stop()


def test_state_and_logs_roots_follow_default_runtime_root():
    env = _env(None)
    try:
        assert paths.state_root() == DEFAULT_ROOT / "state"
        assert paths.logs_root() == DEFAULT_ROOT / "logs"
    finally:
        env.stop()


def test_runtime_root_accepts_absolute_override():
    env = _env(str(OVERRIDE_ROOT))
    try:
        assert paths.runtime_root() == OVERRIDE_ROOT
        assert paths.state_root() == OVERRIDE_ROOT / "state"
        assert paths.logs_root() == OVERRIDE_ROOT / "logs"
    finally:
        env.stop()


def test_relative_override_is_rejected():
    env = _env(RELATIVE_OVERRIDE)
    try:
        try:
            paths.runtime_root()
        except ValueError as raised:
            assert paths.RUNTIME_ROOT_ENV in str(raised)
        else:
            raise AssertionError("relative override must raise ValueError")
    finally:
        env.stop()


def test_empty_override_is_rejected():
    env = _env("")
    try:
        try:
            paths.runtime_root()
        except ValueError:
            pass
        else:
            raise AssertionError("empty override must raise ValueError")
    finally:
        env.stop()


def test_state_and_logs_roots_reject_invalid_override():
    env = _env(RELATIVE_OVERRIDE)
    try:
        for name in ("state_root", "logs_root"):
            try:
                getattr(paths, name)()
            except ValueError:
                pass
            else:
                raise AssertionError(f"{name} must raise on relative override")
    finally:
        env.stop()


def test_invalid_override_does_not_fall_back_to_default():
    env = _env(RELATIVE_OVERRIDE)
    try:
        try:
            paths.runtime_root()
        except ValueError:
            pass
        else:
            raise AssertionError("relative override must raise ValueError")
    finally:
        env.stop()
    env = _env(None)
    try:
        assert paths.runtime_root() == DEFAULT_ROOT
    finally:
        env.stop()


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(
        unittest.FunctionTestCase(function) for function in functions)
