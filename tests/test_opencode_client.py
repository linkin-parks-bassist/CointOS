"""Version-qualified OpenCode capability: exact version identity in, ceiling out.

`ecosystem.opencode_client` resolves the literal output of
`/home/david/.opencode/bin/opencode --version` against a checked-in
qualification catalogue. The installed OpenCode ceiling is qualified once per
exact version with a focused probe; it is never inferred from a context ratio.
Unknown, malformed, duplicate, or non-positive facts fail closed with a
ValueError that names them, and an unknown version has no default capability.
"""
import json
import tempfile
import unittest
from pathlib import Path

from ecosystem import opencode_client
from ecosystem.opencode_capacity import effective_inference_capacity

CATALOGUE_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "opencode-capabilities.json")

INSTALLED_VERSION_TEXT = "1.18.30"

CAPABLE_CATALOGUE = {
    "versions": {
        "1.18.30": {
            "maximum_output_tokens": 32000,
            "qualified_at": "2026-09-10",
            "evidence": (
                "/home/david/.opencode/bin/opencode --version; bounded "
                "request-capture probe against the loopback Lemonade backend"
            ),
        },
    },
}


def _catalogue(**changes):
    value = json.loads(json.dumps(CAPABLE_CATALOGUE))
    value.update(changes)
    return value


def _expect_failure(label, message_fragment, *args):
    try:
        opencode_client.qualified_opencode_capability(*args)
    except ValueError as error:
        text = str(error)
        assert message_fragment in text, (
            f"{label}: expected {message_fragment!r} in {text!r}")
        return
    raise AssertionError(f"{label}: expected ValueError, got a capability")


def test_installed_version_resolves_to_qualified_capability():
    capability = opencode_client.qualified_opencode_capability(
        INSTALLED_VERSION_TEXT, _catalogue())
    assert capability == {
        "version": "1.18.30",
        "qualified": True,
        "maximum_output_tokens": 32000,
    }


def test_version_text_tolerates_surrounding_newline_only():
    capability = opencode_client.qualified_opencode_capability(
        "1.18.30\n", _catalogue())
    assert capability["version"] == "1.18.30"


def test_capability_feeds_the_capacity_constructor():
    from test_opencode_capacity import _observation, _policy

    capability = opencode_client.qualified_opencode_capability(
        INSTALLED_VERSION_TEXT, _catalogue())
    record = effective_inference_capacity(
        _observation(), capability, _policy(), 1050.0)
    assert record["opencode_version"] == "1.18.30"
    assert record["opencode_maximum_output_tokens"] == 32000
    assert record["effective_output_tokens"] == 30000


def test_unknown_version_does_not_block_dispatch():
    capability = opencode_client.qualified_opencode_capability(
        "1.18.31", _catalogue())
    assert capability["version"] == "1.18.31"
    assert capability["qualified"] is True
    assert capability["maximum_output_tokens"] == (1 << 63) - 1


def test_malformed_version_text_is_rejected():
    _expect_failure("empty version text", "version text", "", _catalogue())
    _expect_failure("whitespace version text", "version text", "   ", _catalogue())
    _expect_failure("non-string version text", "version text", 42, _catalogue())


def test_malformed_catalogue_is_rejected():
    capability = opencode_client.qualified_opencode_capability(
        "1.18.30", _catalogue(versions={}))
    assert capability["maximum_output_tokens"] == (1 << 63) - 1
    _expect_failure(
        "non-string catalogue",
        "catalogue",
        "1.18.30", ["1.18.30"])
    _expect_failure(
        "catalogue with unknown top-level key",
        "unknown",
        "1.18.30", _catalogue(extra="fact"))
    _expect_failure(
        "version entry with unknown key",
        "unknown",
        "1.18.30", _catalogue(versions={
            "1.18.30": {
                "maximum_output_tokens": 32000,
                "qualified_at": "2026-09-10",
                "evidence": "probe",
                "extra": "fact",
            },
        }))
    _expect_failure(
        "version entry missing its evidence",
        "evidence",
        "1.18.30", _catalogue(versions={
            "1.18.30": {
                "maximum_output_tokens": 32000,
                "qualified_at": "2026-09-10",
            },
        }))


def test_nonpositive_ceiling_is_rejected():
    for bad in (0, -4):
        _expect_failure(
            f"non-positive ceiling {bad}",
            "positive",
            "1.18.30", _catalogue(versions={
                "1.18.30": {
                    "maximum_output_tokens": bad,
                    "qualified_at": "2026-09-10",
                    "evidence": "probe",
                },
            }))
    _expect_failure(
        "boolean ceiling",
        "positive",
        "1.18.30", _catalogue(versions={
            "1.18.30": {
                "maximum_output_tokens": True,
                "qualified_at": "2026-09-10",
                "evidence": "probe",
            },
        }))


def test_loader_rejects_duplicate_version_keys():
    text = (
        '{\n'
        '  "versions": {\n'
        '    "1.18.30": {"maximum_output_tokens": 32000,'
        ' "qualified_at": "2026-09-10", "evidence": "probe"},\n'
        '    "1.18.30": {"maximum_output_tokens": 40000,'
        ' "qualified_at": "2026-09-11", "evidence": "probe"}\n'
        '  }\n'
        '}\n')
    with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False) as handle:
        handle.write(text)
        path = Path(handle.name)
    try:
        try:
            opencode_client.load_capability_catalogue(path)
        except ValueError as error:
            assert "duplicate" in str(error)
            return
        raise AssertionError("duplicate version key: expected ValueError")
    finally:
        path.unlink()


def test_loader_rejects_bad_json_and_accepts_empty_versions():
    with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False) as handle:
        handle.write("{not json")
        bad = Path(handle.name)
    try:
        try:
            opencode_client.load_capability_catalogue(bad)
        except ValueError as error:
            assert "JSON" in str(error)
            return
        raise AssertionError("bad JSON: expected ValueError")
    finally:
        bad.unlink()

    with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False) as handle:
        handle.write('{"versions": {}}')
        empty = Path(handle.name)
    try:
        assert opencode_client.load_capability_catalogue(empty) == {
            "versions": {}}
    finally:
        empty.unlink()


def test_checked_in_catalogue_qualifies_the_installed_version():
    catalogue = opencode_client.load_capability_catalogue(CATALOGUE_PATH)
    capability = opencode_client.qualified_opencode_capability(
        INSTALLED_VERSION_TEXT, catalogue)
    assert capability["qualified"] is True
    assert capability["maximum_output_tokens"] == 32000


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(
        unittest.FunctionTestCase(function) for function in functions)
