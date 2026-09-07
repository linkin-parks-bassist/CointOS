import unittest

from ecosystem import context_layout

OBSERVED_SHARED_ARGV = [
    "--ctx-size", "262144",
    "--parallel", "8",
    "--kv-unified",
    "--kv-unified-per-slot", "262144",
]

OBSERVED_FIXED_ARGV = [
    "--ctx-size", "262144",
    "--parallel", "2",
]

SHARED_RECORD = {
    "context_mode": "shared",
    "backend_context_tokens": 262144,
    "parallel_sequences": 8,
    "context_tokens_per_sequence": 262144,
    "preallocated_context_tokens": 262144,
}

FIXED_RECORD = {
    "context_mode": "fixed",
    "backend_context_tokens": 262144,
    "parallel_sequences": 2,
    "context_tokens_per_sequence": 131072,
    "preallocated_context_tokens": 262144,
}

RECORD_KEYS = {
    "context_mode",
    "backend_context_tokens",
    "parallel_sequences",
    "context_tokens_per_sequence",
    "preallocated_context_tokens",
}


def _layout(argv, total=262144, slots=8, per_slot=262144, trained=262144):
    return context_layout.observed_context_layout(
        argv, total, slots, per_slot, trained)


def _expect_none(label, argv, total=262144, slots=8, per_slot=262144,
                 trained=262144):
    result = context_layout.observed_context_layout(
        argv, total, slots, per_slot, trained)
    assert result is None, f"{label}: expected None, got {result!r}"


def test_observed_shared_layout_returns_literal_record():
    assert _layout(OBSERVED_SHARED_ARGV) == SHARED_RECORD


def test_observed_fixed_layout_returns_literal_record():
    assert _layout(OBSERVED_FIXED_ARGV, slots=2, per_slot=131072) == FIXED_RECORD


def test_unrelated_flags_pass_untouched():
    argv = [
        "llama-server",
        "/models/qwen3-27b.gguf",
        *OBSERVED_SHARED_ARGV,
        "--mtp", "8",
        "--batch", "512",
        "--prio", "high",
    ]
    assert _layout(argv) == SHARED_RECORD


def test_shared_layout_with_smaller_cap():
    argv = ["--ctx-size", "262144", "--parallel", "8",
            "--kv-unified", "--kv-unified-per-slot", "131072"]
    assert _layout(argv, per_slot=131072) == {
        "context_mode": "shared",
        "backend_context_tokens": 262144,
        "parallel_sequences": 8,
        "context_tokens_per_sequence": 131072,
        "preallocated_context_tokens": 262144,
    }


def test_shared_layout_without_cap():
    argv = ["--ctx-size", "262144", "--parallel", "8", "--kv-unified"]
    assert _layout(argv) == SHARED_RECORD


def test_shared_layout_without_cap_uses_trained_minimum():
    argv = ["--ctx-size", "262144", "--parallel", "8", "--kv-unified"]
    record = _layout(argv, per_slot=131072, trained=131072)
    assert record is not None
    assert record["context_mode"] == "shared"
    assert record["context_tokens_per_sequence"] == 131072


def test_success_record_has_exactly_documented_keys():
    assert set(_layout(OBSERVED_SHARED_ARGV)) == RECORD_KEYS


def test_invalid_numeric_inputs_are_rejected():
    _expect_none("bool total_context", OBSERVED_FIXED_ARGV,
                 total=True, slots=2, per_slot=131072)
    _expect_none("float total_context", OBSERVED_FIXED_ARGV,
                 total=262144.0, slots=2, per_slot=131072)
    _expect_none("string total_context", OBSERVED_FIXED_ARGV,
                 total="262144", slots=2, per_slot=131072)
    _expect_none("zero total_slots", OBSERVED_FIXED_ARGV,
                 slots=0, per_slot=131072)
    _expect_none("negative total_slots", OBSERVED_FIXED_ARGV,
                 slots=-8, per_slot=131072)
    _expect_none("bool per_slot", OBSERVED_FIXED_ARGV,
                 slots=2, per_slot=True)
    _expect_none("zero trained", OBSERVED_FIXED_ARGV,
                 slots=2, per_slot=131072, trained=0)
    _expect_none("None trained", OBSERVED_FIXED_ARGV,
                 slots=2, per_slot=131072, trained=None)


def test_invalid_launch_command_is_rejected():
    _expect_none("non-list launch", "--ctx-size 262144")
    _expect_none("non-string argv entry",
                 ["--ctx-size", "262144", "--parallel", 8])
    _expect_none("empty launch", [])


def test_invalid_flag_forms_are_rejected():
    _expect_none("missing --ctx-size", ["--parallel", "2"], slots=2, per_slot=131072)
    _expect_none("missing --parallel", ["--ctx-size", "262144"],
                 slots=2, per_slot=131072)
    _expect_none("duplicate --ctx-size",
                 ["--ctx-size", "262144", "--ctx-size", "262144",
                  "--parallel", "2"],
                 slots=2, per_slot=131072)
    _expect_none("duplicate --parallel",
                 ["--ctx-size", "262144", "--parallel", "2",
                  "--parallel", "2"],
                 slots=2, per_slot=131072)
    _expect_none("trailing --ctx-size", OBSERVED_FIXED_ARGV + ["--ctx-size"],
                 slots=2, per_slot=131072)
    _expect_none("trailing --parallel",
                 ["--ctx-size", "262144", "--parallel"],
                 slots=2, per_slot=131072)
    _expect_none("ctx value mismatch",
                 ["--ctx-size", "131072", "--parallel", "2"],
                 slots=2, per_slot=131072)
    _expect_none("parallel value mismatch",
                 ["--ctx-size", "262144", "--parallel", "4"],
                 slots=2, per_slot=131072)
    _expect_none("ctx value non-decimal",
                 ["--ctx-size", "26214x", "--parallel", "2"],
                 slots=2, per_slot=131072)
    _expect_none("alias -c",
                 ["-c", "262144", "--ctx-size", "262144", "--parallel", "2"],
                 slots=2, per_slot=131072)
    _expect_none("alias -np",
                 ["--ctx-size", "262144", "-np", "2", "--parallel", "2"],
                 slots=2, per_slot=131072)
    _expect_none("alias -kvu", OBSERVED_SHARED_ARGV + ["-kvu"])
    _expect_none("alias -no-kvu", OBSERVED_SHARED_ARGV + ["-no-kvu"])
    _expect_none("alias --no-kv-unified",
                 OBSERVED_SHARED_ARGV + ["--no-kv-unified"])
    _expect_none("equals --ctx-size",
                 ["--ctx-size=262144", "--parallel", "2"],
                 slots=2, per_slot=131072)
    _expect_none("equals --parallel",
                 ["--ctx-size", "262144", "--parallel=2"],
                 slots=2, per_slot=131072)
    _expect_none("equals --kv-unified",
                 ["--ctx-size", "262144", "--parallel", "8",
                  "--kv-unified=yes"])
    _expect_none("equals cap",
                 ["--ctx-size", "262144", "--parallel", "8",
                  "--kv-unified", "--kv-unified-per-slot=262144"])


def test_invalid_mode_and_contradiction_matrix_is_rejected():
    _expect_none("cap without unified",
                 ["--ctx-size", "262144", "--parallel", "8",
                  "--kv-unified-per-slot", "262144"])
    _expect_none("duplicate --kv-unified",
                 ["--ctx-size", "262144", "--parallel", "8",
                  "--kv-unified", "--kv-unified"])
    _expect_none("duplicate cap",
                 ["--ctx-size", "262144", "--parallel", "8",
                  "--kv-unified", "--kv-unified-per-slot", "262144",
                  "--kv-unified-per-slot", "131072"])
    _expect_none("trailing cap",
                 ["--ctx-size", "262144", "--parallel", "8",
                  "--kv-unified", "--kv-unified-per-slot"])
    _expect_none("cap value zero",
                 ["--ctx-size", "262144", "--parallel", "8",
                  "--kv-unified", "--kv-unified-per-slot", "0"])
    _expect_none("cap value non-decimal",
                 ["--ctx-size", "262144", "--parallel", "8",
                  "--kv-unified", "--kv-unified-per-slot", "half"])
    _expect_none("fixed total not divisible",
                 ["--ctx-size", "262144", "--parallel", "3"],
                 slots=3, per_slot=87381)
    _expect_none("fixed per-slot mismatch",
                 ["--ctx-size", "262144", "--parallel", "2"],
                 slots=2, per_slot=65536)
    _expect_none("fixed per-slot exceeds trained",
                 ["--ctx-size", "262144", "--parallel", "2"],
                 slots=2, per_slot=131072, trained=65536)
    _expect_none("shared cap exceeds total",
                 ["--ctx-size", "262144", "--parallel", "8",
                  "--kv-unified", "--kv-unified-per-slot", "524288"],
                 per_slot=524288)
    _expect_none("shared cap exceeds trained",
                 ["--ctx-size", "262144", "--parallel", "8",
                  "--kv-unified", "--kv-unified-per-slot", "262144"],
                 per_slot=262144, trained=131072)
    _expect_none("shared cap contradicts per-slot",
                 ["--ctx-size", "262144", "--parallel", "8",
                  "--kv-unified", "--kv-unified-per-slot", "131072"],
                 per_slot=262144)
    _expect_none("shared no-cap contradicts per-slot",
                 ["--ctx-size", "262144", "--parallel", "8",
                  "--kv-unified"],
                 per_slot=131072)


def test_inputs_are_not_mutated():
    argv = list(OBSERVED_SHARED_ARGV)
    snapshot = list(argv)
    record = _layout(argv)
    assert record == SHARED_RECORD
    assert argv == snapshot
    bad_argv = ["--ctx-size", "262144"]
    bad_snapshot = list(bad_argv)
    assert _layout(bad_argv) is None
    assert bad_argv == bad_snapshot


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(
        unittest.FunctionTestCase(function) for function in functions)
