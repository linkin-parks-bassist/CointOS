import hashlib
import inspect
import json
import tempfile
import unittest
from pathlib import Path

from survival.configuration import adopt_policy, load_json_policy


def _validator(values):
    if set(values) != {"run_seconds", "lease_seconds"}:
        raise ValueError("unknown or missing timing key")
    if any(type(values[key]) is not int or values[key] <= 0 for key in values):
        raise ValueError("invalid timing value")
    if values["run_seconds"] > values["lease_seconds"]:
        raise ValueError("run_seconds exceeds lease_seconds")


def _active_snapshot():
    return {
        "schema_version": 1,
        "values": {"run_seconds": 5, "lease_seconds": 10},
        "digest": "a" * 64,
        "activated_at": "old",
        "source_path": "policy.json",
    }


def _value_error(operation):
    try:
        operation()
    except ValueError as error:
        return str(error)
    raise AssertionError("expected ValueError")


def test_valid_json_policy_is_parsed_and_validated_as_one_family():
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "policy.json"
        path.write_text('{"run_seconds":5,"lease_seconds":10}', encoding="utf-8")
        assert load_json_policy(path, _validator) == {
            "run_seconds": 5,
            "lease_seconds": 10,
        }


def test_json_policy_rejects_duplicate_keys_and_nonfinite_values():
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "policy.json"
        cases = (
            ('{"run_seconds":5,"run_seconds":6,"lease_seconds":10}', "duplicate JSON field"),
            ('{"run_seconds":NaN,"lease_seconds":10}', "nonfinite policy value"),
            ('{"run_seconds":5,"lease_seconds":Infinity}', "nonfinite policy value"),
        )
        for source, expected in cases:
            path.write_text(source, encoding="utf-8")
            assert expected in _value_error(lambda: load_json_policy(path, _validator))


def test_invalid_policy_never_partially_applies():
    active = _active_snapshot()
    original = json.loads(json.dumps(active))
    result, error = adopt_policy(
        active,
        {"run_seconds": -1, "lease_seconds": 10},
        _validator,
        {"boot_id": "b", "monotonic": 10, "utc": "new"},
    )
    assert result is active
    assert result == original
    assert error == "invalid timing value"


def test_unknown_keys_and_invalid_relationships_preserve_the_prior_snapshot():
    active = _active_snapshot()
    cases = (
        ({"run_seconds": 5, "lease_seconds": 10, "command": "restart"},
         "unknown or missing timing key"),
        ({"run_seconds": 11, "lease_seconds": 10}, "run_seconds exceeds lease_seconds"),
    )
    for proposed, expected in cases:
        result, error = adopt_policy(
            active, proposed, _validator,
            {"boot_id": "b", "monotonic": 10, "utc": "new"},
        )
        assert result is active
        assert error == expected


def test_valid_policy_publishes_one_canonical_snapshot():
    active = _active_snapshot()
    proposed = {"run_seconds": 6, "lease_seconds": 12}
    clock = {"boot_id": "b", "monotonic": 10, "utc": "new"}
    expected_digest = hashlib.sha256(
        b'{"lease_seconds":12,"run_seconds":6}'
    ).hexdigest()
    result, error = adopt_policy(active, proposed, _validator, clock)
    assert error is None
    assert result == {
        "schema_version": 1,
        "values": proposed,
        "digest": expected_digest,
        "activated_at": "new",
        "source_path": "policy.json",
    }
    assert result["values"] is not proposed


def test_no_accepted_boot_snapshot_is_an_explicit_failure():
    result, error = adopt_policy(
        {}, {"run_seconds": 5, "lease_seconds": 10}, _validator,
        {"boot_id": "b", "monotonic": 10, "utc": "new"},
    )
    assert result == {}
    assert error == "no accepted policy snapshot"


def test_publication_failure_preserves_the_prior_snapshot():
    active = _active_snapshot()
    proposed = {"run_seconds": 5, "lease_seconds": 10}
    proposed["cycle"] = proposed

    def accept_cycle(values):
        return None

    result, error = adopt_policy(
        active, proposed, accept_cycle,
        {"boot_id": "b", "monotonic": 10, "utc": "new"},
    )
    assert result is active
    assert error == "policy publication failed: Circular reference detected"


def load_tests(_loader, _tests, _pattern):
    functions = [
        value for name, value in globals().items()
        if name.startswith("test_") and inspect.isfunction(value)
    ]
    return unittest.TestSuite(unittest.FunctionTestCase(value) for value in functions)
