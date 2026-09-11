import json
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "workspaces.json"
KNOWLEDGE = str(ROOT / ".knowledge")
EXPECTED_READ_PATHS = (
    KNOWLEDGE,
    str(ROOT / "ecosystem"),
    str(ROOT / "roles"),
    str(ROOT / "tests"),
)
EXPECTED_WRITE_PATHS = (KNOWLEDGE,)


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
    assert read_paths == list(EXPECTED_READ_PATHS), (
        f"unexpected cointos ambient read paths: {read_paths}")


def test_cointos_ambient_write_paths_match_current_tree():
    entry = _cointos_entry()
    write_paths = entry["ambient_write_paths"]
    _assert_ambient_paths(entry, write_paths, "write")
    assert write_paths == list(EXPECTED_WRITE_PATHS), (
        f"unexpected cointos ambient write paths: {write_paths}")


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(
        unittest.FunctionTestCase(function) for function in functions)
