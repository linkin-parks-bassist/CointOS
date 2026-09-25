"""Validate user systemd declarations of the CointOS runtime root.

Data-oriented checks over the repository unit files under
``services/systemd``. No live services are started or inspected.
"""

from pathlib import Path

import unittest

from ecosystem import paths

REPO_ROOT = Path(__file__).resolve().parents[1]
UNIT_DIR = REPO_ROOT / "services" / "systemd"
ENV_NAME = "COINTOS_RUNTIME_ROOT"
PORTABLE_VALUE = "%h/.CointOS"
DECLARATION = f"{ENV_NAME}={PORTABLE_VALUE}"

# User services that launch CointOS Python code which may consume mutable
# runtime state. agent-models.service launches only the external Lemonade
# binary, and the .path, .timer, and .slice units launch no Python code.
EXPECTED_UNITS = (
    "agent-backend-profile.service",
    "agent-control-worker.service",
    "agent-ecosystem.service",
    "agent-executor@.service",
    "agent-inference-proxy.service",
    "agent-notifier.service",
    "agent-resource-guard.service",
    "agent-telegram.service",
    "agent-watchdog.service",
)


def _environment_assignments(unit_path):
    assignments = []
    section = None
    for raw in unit_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if section == "Service" and key == "Environment":
            assignments.append(value.strip())
    return assignments


def _runtime_root_declarations():
    found = {}
    for unit_path in sorted(UNIT_DIR.glob("*.service")):
        declarations = [line for line in _environment_assignments(unit_path)
                        if line.split("=", 1)[0] == ENV_NAME]
        if declarations:
            found[unit_path.name] = declarations
    return found


def test_expected_units_declare_the_portable_runtime_root():
    declared = _runtime_root_declarations()
    for name in EXPECTED_UNITS:
        unit_path = UNIT_DIR / name
        assert unit_path.is_file(), f"missing unit {name}"
        assert declared.get(name) == [DECLARATION], (
            f"{name} must declare exactly {DECLARATION!r}, "
            f"got {declared.get(name)!r}")


def test_portable_runtime_root_expands_to_the_paths_owner_default():
    assert ENV_NAME == paths.RUNTIME_ROOT_ENV
    assert PORTABLE_VALUE.startswith("%h/"), (
        f"portable declaration must use the %h home specifier, "
        f"got {PORTABLE_VALUE!r}")
    expanded = Path(PORTABLE_VALUE.replace("%h", str(Path.home())))
    assert expanded == paths.DEFAULT_RUNTIME_ROOT, (
        f"portable declaration {PORTABLE_VALUE!r} expands to {expanded}, "
        f"expected {paths.DEFAULT_RUNTIME_ROOT}")


def test_only_expected_units_declare_the_runtime_root():
    assert set(_runtime_root_declarations()) == set(EXPECTED_UNITS)


def test_no_repo_relative_runtime_root():
    for name, declarations in _runtime_root_declarations().items():
        for declaration in declarations:
            value = declaration.split("=", 1)[1].replace(
                "%h", str(Path.home()))
            candidate = Path(value)
            assert candidate.is_absolute(), (
                f"{name}: {declaration!r} names a repo-relative runtime root")
            assert REPO_ROOT not in candidate.parents, (
                f"{name}: runtime root {candidate} is inside the source "
                "checkout")
            assert candidate != REPO_ROOT, (
                f"{name}: runtime root is the source checkout")


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(
        unittest.FunctionTestCase(function) for function in functions)
