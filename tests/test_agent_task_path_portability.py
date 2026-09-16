import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXED_HOME_PREFIX = "/home/david/"
AGENT_FACING_SOURCES = (
    REPO_ROOT / "ecosystem" / "watchdog.py",
    REPO_ROOT / "ecosystem" / "resource_control.py",
)
PORTABLE_REFERENCES = {
    "watchdog.py": (
        "Work from `{cli.ROOT}`",
        '`{cli.ROOT / "state/conversations"}`',
    ),
    "resource_control.py": (
        "`~/Projects/CointOS/scripts/resource-control recover`",
    ),
}


def test_agent_facing_sources_exist():
    for path in AGENT_FACING_SOURCES:
        assert path.is_file(), f"missing agent-facing source {path}"


def test_agent_facing_sources_contain_no_fixed_home_paths():
    violations = []
    for path in AGENT_FACING_SOURCES:
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if FIXED_HOME_PREFIX in line:
                violations.append(f"{path.name}:{line_no}: {line.strip()}")
    assert not violations, (
        "fixed /home/david/ paths in agent-facing sources:\n" + "\n".join(violations))


def test_agent_facing_strings_use_portable_spelling():
    for path in AGENT_FACING_SOURCES:
        text = path.read_text(encoding="utf-8")
        for reference in PORTABLE_REFERENCES[path.name]:
            assert reference in text, (
                f"{path.name} lost the portable {reference} reference")


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(
        unittest.FunctionTestCase(function) for function in functions)
