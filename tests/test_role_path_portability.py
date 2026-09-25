import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXED_HOME_PREFIX = "/home/david/"


def _role_markdown_paths():
    return sorted((REPO_ROOT / "roles").glob("*.md"))


def _fixed_home_violations():
    violations = []
    for path in _role_markdown_paths():
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if FIXED_HOME_PREFIX in line:
                violations.append(f"{path.name}:{line_no}: {line.strip()}")
    return violations


def test_role_markdown_files_exist():
    paths = _role_markdown_paths()
    assert paths, "no role Markdown found under roles/"
    for name in ("_base", "_control-plane", "manager", "sole_survivor", "steward", "worker"):
        assert REPO_ROOT / "roles" / f"{name}.md" in paths, f"missing roles/{name}.md"


def test_role_markdown_contains_no_fixed_home_paths():
    violations = _fixed_home_violations()
    assert not violations, (
        "fixed /home/david/ paths in role Markdown:\n" + "\n".join(violations))


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(
        unittest.FunctionTestCase(function) for function in functions)
