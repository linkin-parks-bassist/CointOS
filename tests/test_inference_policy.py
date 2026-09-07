import tempfile
import unittest
from pathlib import Path

from ecosystem import inference_policy

REPO_ROOT = Path(__file__).resolve().parents[1]

CANONICAL_POLICY = {
    "work_slots": 2,
    "front_slots": 1,
    "context_tokens_per_slot": 131072,
    "backend_context_tokens": 262144,
}

CANONICAL_TEXT = (
    "[inference]\n"
    "work_slots = 2\n"
    "front_slots = 1\n"
    "context_tokens_per_slot = 131072\n"
)

INVALID_POLICIES = (
    ("empty file", ""),
    ("missing [inference] section",
     "[model:fast]\nwork_slots = 4\n"),
    ("missing required key",
     "[inference]\nwork_slots = 2\nfront_slots = 1\n"),
    ("unknown key in [inference]",
     "[inference]\nwork_slots = 2\nfront_slots = 1\n"
     "context_tokens_per_slot = 131072\nextra = 1\n"),
    ("zero value",
     "[inference]\nwork_slots = 0\nfront_slots = 1\n"
     "context_tokens_per_slot = 131072\n"),
    ("negative value",
     "[inference]\nwork_slots = 2\nfront_slots = -1\n"
     "context_tokens_per_slot = 131072\n"),
    ("fractional value",
     "[inference]\nwork_slots = 2.0\nfront_slots = 1\n"
     "context_tokens_per_slot = 131072\n"),
    ("non-integer value",
     "[inference]\nwork_slots = two\nfront_slots = 1\n"
     "context_tokens_per_slot = 131072\n"),
    ("duplicate section",
     "[inference]\nwork_slots = 2\nfront_slots = 1\n"
     "context_tokens_per_slot = 131072\n[inference]\nwork_slots = 3\n"),
    ("duplicate key",
     "[inference]\nwork_slots = 2\nwork_slots = 3\nfront_slots = 1\n"
     "context_tokens_per_slot = 131072\n"),
    ("unknown section",
     "[inference]\nwork_slots = 2\nfront_slots = 1\n"
     "context_tokens_per_slot = 131072\n[backend]\nwork_slots = 1\n"),
    ("empty model override",
     "[inference]\nwork_slots = 2\nfront_slots = 1\n"
     "context_tokens_per_slot = 131072\n[model:fast]\n"),
    ("front_slots inside model override",
     "[inference]\nwork_slots = 2\nfront_slots = 1\n"
     "context_tokens_per_slot = 131072\n[model:fast]\nfront_slots = 2\n"),
    ("empty model name",
     "[inference]\nwork_slots = 2\nfront_slots = 1\n"
     "context_tokens_per_slot = 131072\n[model:]\nwork_slots = 2\n"),
    ("malformed value in unselected model override",
     "[inference]\nwork_slots = 2\nfront_slots = 1\n"
     "context_tokens_per_slot = 131072\n[model:slow]\n"
     "context_tokens_per_slot = 1.5\n"),
    ("DEFAULT section values",
     "[DEFAULT]\nwork_slots = 2\nfront_slots = 1\n"
     "context_tokens_per_slot = 131072\n[inference]\nwork_slots = 2\n"
     "front_slots = 1\ncontext_tokens_per_slot = 131072\n"),
    ("option before section header",
     "work_slots = 2\n[inference]\nfront_slots = 1\n"
     "context_tokens_per_slot = 131072\n"),
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


def test_committed_candidate_config_loads_exact_default_result():
    path = REPO_ROOT / "config" / "inference.cfg"
    result = inference_policy.load_inference_policy(path)
    assert result == CANONICAL_POLICY


def test_exact_default_result_from_temporary_root():
    with tempfile.TemporaryDirectory(prefix="inference-policy-") as temporary:
        path = _write_policy(Path(temporary), CANONICAL_TEXT)
        result = inference_policy.load_inference_policy(path)
    assert result == CANONICAL_POLICY
    assert set(result) == {
        "work_slots", "front_slots", "context_tokens_per_slot",
        "backend_context_tokens",
    }


def test_selected_override_changes_only_named_fields_and_not_globals():
    text = (
        CANONICAL_TEXT
        + "\n"
        "[model:wide]\n"
        "work_slots = 4\n"
        "context_tokens_per_slot = 32768\n"
        "\n"
        "[model:narrow]\n"
        "context_tokens_per_slot = 8192\n"
    )
    with tempfile.TemporaryDirectory(prefix="inference-policy-") as temporary:
        path = _write_policy(Path(temporary), text)
        wide = inference_policy.load_inference_policy(path, "wide")
        narrow = inference_policy.load_inference_policy(path, "narrow")
        defaults = inference_policy.load_inference_policy(path)
        absent = inference_policy.load_inference_policy(path, "not-a-model")
    assert wide == {
        "work_slots": 4,
        "front_slots": 1,
        "context_tokens_per_slot": 32768,
        "backend_context_tokens": 131072,
    }
    assert narrow == {
        "work_slots": 2,
        "front_slots": 1,
        "context_tokens_per_slot": 8192,
        "backend_context_tokens": 16384,
    }
    assert defaults == CANONICAL_POLICY
    assert absent == CANONICAL_POLICY


def test_unselected_malformed_override_is_still_rejected():
    text = (
        CANONICAL_TEXT
        + "\n"
        "[model:fast]\n"
        "work_slots = 4\n"
        "\n"
        "[model:slow]\n"
        "context_tokens_per_slot = 0\n"
    )
    with tempfile.TemporaryDirectory(prefix="inference-policy-") as temporary:
        path = _write_policy(Path(temporary), text)
        for label, model_id in (
            ("selected healthy section", "fast"),
            ("no model selected", None),
            ("selected malformed section", "slow"),
        ):
            _expect_value_error(path, label, model_id)


def test_invalid_config_matrix_is_rejected():
    for label, text in INVALID_POLICIES:
        with tempfile.TemporaryDirectory(prefix="inference-policy-") as temporary:
            path = _write_policy(Path(temporary), text)
            _expect_value_error(path, label)


def test_missing_or_unreadable_file_is_value_error():
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
