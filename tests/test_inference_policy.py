"""Tests for the candidate global INI inference context-allocation policy.

Each test names the bug it guards before its assertions. The committed
candidate config is shared; fixed mode remains supported.
"""

import tempfile
import unittest
from pathlib import Path

from ecosystem import inference_policy

REPO_ROOT = Path(__file__).resolve().parents[1]

CANONICAL_KEYS = {
    "work_slots", "front_slots", "context_tokens_per_slot",
    "backend_context_tokens", "context_mode",
}

FULL_FIXED_INI = (
    "[inference]\n"
    "work_slots = 2\n"
    "front_slots = 1\n"
    "context_tokens_per_slot = 131072\n"
    "backend_context_tokens = 262144\n"
    "context_mode = fixed\n"
)

INVALID_POLICIES = (
    ("empty file", ""),
    ("missing [inference] section",
     "[model:fast]\nwork_slots = 4\n"),
    ("missing required key",
     "[inference]\nwork_slots = 2\nfront_slots = 1\n"
     "context_tokens_per_slot = 131072\nbackend_context_tokens = 262144\n"),
    ("unknown key in [inference]",
     FULL_FIXED_INI + "extra = 1\n"),
    ("zero value",
     "[inference]\nwork_slots = 0\nfront_slots = 1\n"
     "context_tokens_per_slot = 131072\nbackend_context_tokens = 262144\n"
     "context_mode = fixed\n"),
    ("negative value",
     "[inference]\nwork_slots = 2\nfront_slots = -1\n"
     "context_tokens_per_slot = 131072\nbackend_context_tokens = 262144\n"
     "context_mode = fixed\n"),
    ("fractional value",
     "[inference]\nwork_slots = 2.0\nfront_slots = 1\n"
     "context_tokens_per_slot = 131072\nbackend_context_tokens = 262144\n"
     "context_mode = fixed\n"),
    ("non-integer value",
     "[inference]\nwork_slots = two\nfront_slots = 1\n"
     "context_tokens_per_slot = 131072\nbackend_context_tokens = 262144\n"
     "context_mode = fixed\n"),
    ("invalid context_mode",
     "[inference]\nwork_slots = 2\nfront_slots = 1\n"
     "context_tokens_per_slot = 131072\nbackend_context_tokens = 262144\n"
     "context_mode = reserved\n"),
    ("duplicate section",
     FULL_FIXED_INI + "[inference]\nwork_slots = 3\n"),
    ("duplicate key",
     "[inference]\nwork_slots = 2\nwork_slots = 3\nfront_slots = 1\n"
     "context_tokens_per_slot = 131072\nbackend_context_tokens = 262144\n"
     "context_mode = fixed\n"),
    ("unknown section",
     FULL_FIXED_INI + "[backend]\nwork_slots = 1\n"),
    ("empty model override",
     FULL_FIXED_INI + "[model:fast]\n"),
    ("front_slots inside model override",
     FULL_FIXED_INI + "[model:fast]\nfront_slots = 2\n"),
    ("empty model name",
     FULL_FIXED_INI + "[model:]\nwork_slots = 2\n"),
    ("malformed value in unselected model override",
     FULL_FIXED_INI + "[model:slow]\ncontext_tokens_per_slot = 1.5\n"),
    ("DEFAULT section values",
     "[DEFAULT]\nwork_slots = 2\nfront_slots = 1\n"
     "context_tokens_per_slot = 131072\nbackend_context_tokens = 262144\n"
     "context_mode = fixed\n[inference]\nwork_slots = 2\nfront_slots = 1\n"
     "context_tokens_per_slot = 131072\nbackend_context_tokens = 262144\n"
     "context_mode = fixed\n"),
    ("option before section header",
     "work_slots = 2\n[inference]\nfront_slots = 1\n"
     "context_tokens_per_slot = 131072\nbackend_context_tokens = 262144\n"
     "context_mode = fixed\n"),
)


def _write_policy(root: Path, text: str) -> Path:
    path = root / "inference.cfg"
    path.write_text(text, encoding="utf-8")
    return path


def _expect_value_error(path: Path, label: str,
                        model_id: str | None = None) -> None:
    try:
        inference_policy.load_inference_policy(path, model_id)
    except ValueError:
        return
    raise AssertionError(f"ValueError not raised: {label} model_id={model_id!r}")


def test_fixed_total_matching_slots_times_per_slot_loads():
    """Bug guarded: a consistent fixed allocation (2 slots x 131072 = 262144)
    must load and return exactly the five canonical keys, with
    backend_context_tokens read from the file, not recomputed."""
    with tempfile.TemporaryDirectory(prefix="inference-policy-") as temporary:
        path = _write_policy(Path(temporary), FULL_FIXED_INI)
        result = inference_policy.load_inference_policy(path)
    assert result == {
        "work_slots": 2,
        "front_slots": 1,
        "context_tokens_per_slot": 131072,
        "backend_context_tokens": 262144,
        "context_mode": "fixed",
    }
    assert set(result) == CANONICAL_KEYS


def test_shared_pool_equal_to_per_slot_cap_loads():
    """Bug guarded: shared mode must accept eight slots with cap 262144 and
    pool 262144; the old fixed coupling (pool == slots * cap) must not be
    imposed on shared mode."""
    text = (
        "[inference]\n"
        "work_slots = 8\n"
        "front_slots = 1\n"
        "context_tokens_per_slot = 262144\n"
        "backend_context_tokens = 262144\n"
        "context_mode = shared\n"
    )
    with tempfile.TemporaryDirectory(prefix="inference-policy-") as temporary:
        path = _write_policy(Path(temporary), text)
        result = inference_policy.load_inference_policy(path)
    assert result == {
        "work_slots": 8,
        "front_slots": 1,
        "context_tokens_per_slot": 262144,
        "backend_context_tokens": 262144,
        "context_mode": "shared",
    }


def test_shared_pool_larger_than_per_slot_cap_loads():
    """Bug guarded: shared mode must accept pool 262144 greater than the
    per-slot cap 131072; only the pool >= cap rule applies, not a slot
    count coupling."""
    text = (
        "[inference]\n"
        "work_slots = 8\n"
        "front_slots = 1\n"
        "context_tokens_per_slot = 131072\n"
        "backend_context_tokens = 262144\n"
        "context_mode = shared\n"
    )
    with tempfile.TemporaryDirectory(prefix="inference-policy-") as temporary:
        path = _write_policy(Path(temporary), text)
        result = inference_policy.load_inference_policy(path)
    assert result == {
        "work_slots": 8,
        "front_slots": 1,
        "context_tokens_per_slot": 131072,
        "backend_context_tokens": 262144,
        "context_mode": "shared",
    }


def test_selected_model_override_merges_over_globals():
    """Bug guarded: a selected [model:NAME] override must merge over the
    globals (work_slots 4 and pool 524288 over shared globals), while an
    unselected or absent selection keeps the globals intact."""
    text = (
        "[inference]\n"
        "work_slots = 8\n"
        "front_slots = 1\n"
        "context_tokens_per_slot = 262144\n"
        "backend_context_tokens = 262144\n"
        "context_mode = shared\n"
        "\n"
        "[model:wide]\n"
        "work_slots = 4\n"
        "backend_context_tokens = 524288\n"
    )
    with tempfile.TemporaryDirectory(prefix="inference-policy-") as temporary:
        path = _write_policy(Path(temporary), text)
        wide = inference_policy.load_inference_policy(path, "wide")
        unselected = inference_policy.load_inference_policy(path)
        absent = inference_policy.load_inference_policy(path, "not-a-model")
    assert wide == {
        "work_slots": 4,
        "front_slots": 1,
        "context_tokens_per_slot": 262144,
        "backend_context_tokens": 524288,
        "context_mode": "shared",
    }
    assert unselected == absent == {
        "work_slots": 8,
        "front_slots": 1,
        "context_tokens_per_slot": 262144,
        "backend_context_tokens": 262144,
        "context_mode": "shared",
    }


def test_inconsistent_fixed_total_is_rejected():
    """Bug guarded: fixed mode must reject a pool that is not
    work_slots * context_tokens_per_slot (2 * 131072 != 200000)."""
    text = (
        "[inference]\n"
        "work_slots = 2\n"
        "front_slots = 1\n"
        "context_tokens_per_slot = 131072\n"
        "backend_context_tokens = 200000\n"
        "context_mode = fixed\n"
    )
    with tempfile.TemporaryDirectory(prefix="inference-policy-") as temporary:
        path = _write_policy(Path(temporary), text)
        _expect_value_error(path, "inconsistent fixed total")


def test_shared_pool_smaller_than_per_slot_cap_is_rejected():
    """Bug guarded: shared mode must reject a per-slot cap larger than the
    shared pool (cap 262144 > pool 131072)."""
    text = (
        "[inference]\n"
        "work_slots = 8\n"
        "front_slots = 1\n"
        "context_tokens_per_slot = 262144\n"
        "backend_context_tokens = 131072\n"
        "context_mode = shared\n"
    )
    with tempfile.TemporaryDirectory(prefix="inference-policy-") as temporary:
        path = _write_policy(Path(temporary), text)
        _expect_value_error(path, "shared cap larger than pool")


def test_unselected_merged_override_is_still_validated():
    """Bug guarded: every [model:NAME] override must be validated merged over
    the globals even when unselected: [model:slow] pool 100000 breaks the
    fixed total 2 * 131072 = 262144 and must be rejected for any selection,
    including none."""
    text = (
        FULL_FIXED_INI
        + "\n"
        "[model:fast]\n"
        "work_slots = 4\n"
        "backend_context_tokens = 524288\n"
        "\n"
        "[model:slow]\n"
        "backend_context_tokens = 100000\n"
    )
    with tempfile.TemporaryDirectory(prefix="inference-policy-") as temporary:
        path = _write_policy(Path(temporary), text)
        for label, model_id in (
            ("selected healthy section", "fast"),
            ("no model selected", None),
            ("selected malformed section", "slow"),
        ):
            _expect_value_error(path, label, model_id)


def test_committed_candidate_config_is_a_valid_policy():
    """Bug guarded: the committed candidate config must load and satisfy the
    policy rules without pinning work_slots=8 as a permanent product limit."""
    path = REPO_ROOT / "config" / "inference.cfg"
    result = inference_policy.load_inference_policy(path)
    assert set(result) == CANONICAL_KEYS
    for key in ("work_slots", "front_slots", "context_tokens_per_slot",
                "backend_context_tokens"):
        assert isinstance(result[key], int)
        assert result[key] > 0
    if result["context_mode"] == "fixed":
        assert result["backend_context_tokens"] == (
            result["work_slots"] * result["context_tokens_per_slot"]
        )
    else:
        assert result["backend_context_tokens"] >= result["context_tokens_per_slot"]


def test_invalid_config_matrix_is_rejected():
    """Bug guarded: strict duplicates, malformed values, unknown keys and
    sections, empty or front_slots-only overrides, and DEFAULT values must
    all be rejected under the canonical five-key schema."""
    for label, text in INVALID_POLICIES:
        with tempfile.TemporaryDirectory(prefix="inference-policy-") as temporary:
            path = _write_policy(Path(temporary), text)
            _expect_value_error(path, label)


def test_missing_or_unreadable_file_is_value_error():
    """Bug guarded: a missing path or a directory where a file is expected
    must raise ValueError, not an OSError."""
    with tempfile.TemporaryDirectory(prefix="inference-policy-") as temporary:
        root = Path(temporary)
        missing = root / "absent" / "inference.cfg"
        directory = root / "directory.cfg"
        directory.mkdir()
        _expect_value_error(missing, "missing file")
        _expect_value_error(directory, "unreadable path")


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
