import json
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "workspaces.json"
KNOWLEDGE = str(ROOT / ".knowledge")
PRESERVED_READ_PATHS = (
    str(ROOT / "ecosystem"),
    str(ROOT / "roles"),
    str(ROOT / "tests"),
)


def _cointos_entry():
    values = json.loads(REGISTRY.read_text(encoding="utf-8"))
    entry = next((item for item in values["workspaces"]
                  if item["id"] == "cointos"), None)
    if entry is None:
        raise AssertionError("cointos workspace entry is missing")
    return entry


def _assert_ambient_paths(entry, paths, kind):
    workspace = Path(entry["path"])
    assert workspace == ROOT, "cointos workspace is not this repository"
    assert workspace.is_dir(), "cointos workspace does not exist"
    assert type(paths) is list and paths, f"cointos {kind} paths are missing"
    for path in paths:
        assert os.path.isabs(path), f"cointos {kind} path is not absolute: {path}"
        try:
            contained = os.path.commonpath([path, str(workspace)]) == str(workspace)
        except ValueError:
            contained = False
        assert contained, f"cointos {kind} path escapes the workspace: {path}"
        assert Path(path).is_dir(), f"cointos {kind} path names an absent path: {path}"


def test_cointos_ambient_read_paths_match_current_tree():
    entry = _cointos_entry()
    read_paths = entry["ambient_read_paths"]
    _assert_ambient_paths(entry, read_paths, "read")
    assert KNOWLEDGE in read_paths, "ambient reads do not include .knowledge"
    for path in PRESERVED_READ_PATHS:
        assert path in read_paths, f"ambient reads lost the {path} read path"


def test_cointos_ambient_write_paths_match_current_tree():
    entry = _cointos_entry()
    write_paths = entry["ambient_write_paths"]
    _assert_ambient_paths(entry, write_paths, "write")
    assert KNOWLEDGE in write_paths, "ambient writes do not include .knowledge"
    assert str(ROOT / "agent_notes") not in write_paths, \
        "deprecated agent_notes is still an ambient write path"


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(
        unittest.FunctionTestCase(function) for function in functions)
