"""Pure effective-capacity record: live evidence in, launch limits out.

The record under test is the plain-data output of
`ecosystem.opencode_capacity.effective_inference_capacity`. It must be
derivable only from a fresh, incarnation-bound backend observation, a
version-qualified OpenCode capability, and an explicit policy; every
contradictory, stale, or unknown input fails closed with a ValueError
that names the disagreeing facts.
"""
import copy
import unittest

from ecosystem import context_layout
from ecosystem.opencode_capacity import (
    effective_inference_capacity,
    launch_fingerprint,
)

FIXED_LAYOUT = {
    "context_mode": "fixed",
    "backend_context_tokens": 131072,
    "parallel_sequences": 4,
    "context_tokens_per_sequence": 32768,
    "preallocated_context_tokens": 131072,
}

SHARED_LAYOUT = {
    "context_mode": "shared",
    "backend_context_tokens": 262144,
    "parallel_sequences": 8,
    "context_tokens_per_sequence": 262144,
    "preallocated_context_tokens": 262144,
}

FIXED_LAUNCH = [
    "llama-server",
    "/models/qwen3.8-27b.gguf",
    "--ctx-size", "131072",
    "--parallel", "4",
]

SHARED_LAUNCH = [
    "llama-server",
    "/models/qwen3.8-27b.gguf",
    "--ctx-size", "262144",
    "--parallel", "8",
    "--kv-unified",
    "--kv-unified-per-slot", "262144",
]

FIXED_FINGERPRINT = launch_fingerprint(FIXED_LAUNCH)
SHARED_FINGERPRINT = launch_fingerprint(SHARED_LAUNCH)

CLIENT = {
    "version": "1.18.30",
    "qualified": True,
    "maximum_output_tokens": 32000,
}

POLICY = {
    "output_reserve_tokens": 30000,
    "rollover_fraction": 0.75,
    "max_age_seconds": 300,
}

OBSERVED_AT = 1000.0
NOW = 1050.0

OBSERVATION = {
    "selected_model_id": "qwen3.8-27b",
    "observed_model_id": "qwen3.8-27b",
    "backend_incarnation": {
        "backend_url": "http://127.0.0.1:13307/v1",
        "pid": 4242,
        "launch_command": list(FIXED_LAUNCH),
        "launch_fingerprint": FIXED_FINGERPRINT,
    },
    "layout": dict(FIXED_LAYOUT),
    "observed_at": OBSERVED_AT,
    "evidence": "lemonade:/api/v1/health;127.0.0.1:13307/v1/models;/props",
    "prompt_estimate_tokens": 2000,
    "backend_output_ceiling": None,
}


def _observation(**changes):
    value = copy.deepcopy(OBSERVATION)
    value.update(copy.deepcopy(changes))
    return value


def _client(**changes):
    value = copy.deepcopy(CLIENT)
    value.update(copy.deepcopy(changes))
    return value


def _policy(**changes):
    value = copy.deepcopy(POLICY)
    value.update(copy.deepcopy(changes))
    return value


def _expect_failure(label, message_fragment, observation, client, policy, now=NOW):
    try:
        effective_inference_capacity(observation, client, policy, now)
    except ValueError as error:
        text = str(error)
        assert message_fragment in text, (
            f"{label}: expected {message_fragment!r} in {text!r}")
        return
    raise AssertionError(f"{label}: expected ValueError, got a record")


def test_fixed_layout_derives_canonical_record():
    record = effective_inference_capacity(
        _observation(), _client(), _policy(), NOW)
    assert record == {
        "model_id": "qwen3.8-27b",
        "backend_incarnation": {
            "backend_url": "http://127.0.0.1:13307/v1",
            "pid": 4242,
            "launch_command": list(FIXED_LAUNCH),
            "launch_fingerprint": FIXED_FINGERPRINT,
        },
        "observed_at": OBSERVED_AT,
        "evidence": "lemonade:/api/v1/health;127.0.0.1:13307/v1/models;/props",
        "context_mode": "fixed",
        "backend_context_tokens": 131072,
        "parallel_sequences": 4,
        "effective_context_tokens": 32768,
        "opencode_version": "1.18.30",
        "opencode_maximum_output_tokens": 32000,
        "effective_output_tokens": 30000,
        "output_reserve_tokens": 30000,
        "rollover_fraction": 0.75,
        "rollover_threshold_tokens": 24576,
        "prompt_estimate_tokens": 2000,
        "opencode_context_tokens": 32768,
        "opencode_output_tokens": 30000,
        "derived_from": (
            "lemonade:/api/v1/health;127.0.0.1:13307/v1/models;/props;"
            "opencode:1.18.30"
        ),
    }


def test_shared_layout_keeps_observed_per_request_cap():
    observation = _observation(
        selected_model_id="qwen3.8-27b",
        layout=dict(SHARED_LAYOUT),
        backend_incarnation={
            "backend_url": "http://127.0.0.1:13308/v1",
            "pid": 4343,
            "launch_command": list(SHARED_LAUNCH),
            "launch_fingerprint": SHARED_FINGERPRINT,
        },
    )
    record = effective_inference_capacity(observation, _client(), _policy(), NOW)
    assert record["context_mode"] == "shared"
    assert record["backend_context_tokens"] == 262144
    assert record["parallel_sequences"] == 8
    # The per-request cap is the observed per-slot value, never the pool
    # re-divided and never the pool itself.
    assert record["effective_context_tokens"] == 262144
    assert record["opencode_context_tokens"] == 262144
    # Rollover uses the same effective denominator: 0.75 * 262144.
    assert record["rollover_threshold_tokens"] == 196608
    assert record["model_id"] == "qwen3.8-27b"
    assert record["backend_incarnation"]["pid"] == 4343


def test_layout_record_comes_from_the_layout_owner():
    assert context_layout.observed_context_layout(
        FIXED_LAUNCH, 131072, 4, 32768, 262144) == FIXED_LAYOUT
    assert context_layout.observed_context_layout(
        SHARED_LAUNCH, 262144, 8, 262144, 262144) == SHARED_LAYOUT


def test_effective_output_is_smallest_qualified_ceiling():
    client = _client(maximum_output_tokens=20000)
    observation = _observation(backend_output_ceiling=25000)
    record = effective_inference_capacity(observation, client, _policy(), NOW)
    assert record["opencode_maximum_output_tokens"] == 20000
    assert record["effective_output_tokens"] == 20000
    assert record["opencode_output_tokens"] == 20000


def test_output_reserve_bounds_effective_output():
    record = effective_inference_capacity(
        _observation(), _client(), _policy(output_reserve_tokens=10000), NOW)
    assert record["effective_output_tokens"] == 10000
    assert record["output_reserve_tokens"] == 10000


def test_rollover_threshold_uses_effective_denominator():
    record = effective_inference_capacity(
        _observation(), _client(), _policy(rollover_fraction=0.5), NOW)
    assert record["rollover_threshold_tokens"] == 16384
    # The threshold must be reachable before the backend limit.
    assert record["rollover_threshold_tokens"] < record["effective_context_tokens"]
    assert record["prompt_estimate_tokens"] + record["effective_output_tokens"] \
        <= record["effective_context_tokens"]


def test_inputs_are_not_mutated():
    observation = _observation()
    client = _client()
    policy = _policy()
    snapshot = (copy.deepcopy(observation), copy.deepcopy(client),
                copy.deepcopy(policy))
    effective_inference_capacity(observation, client, policy, NOW)
    assert (observation, client, policy) == snapshot


def test_model_mismatch_is_rejected():
    _expect_failure(
        "selected model differs from the observed backend model",
        "qwen3.8-27b",
        _observation(selected_model_id="other-model"), _client(), _policy())


def test_backend_incarnation_mismatch_is_rejected():
    # The fingerprint binds the layout to the exact launch it was observed
    # from; a launch command that no longer matches is a different
    # incarnation, even if every field is individually well formed.
    _expect_failure(
        "differently incarnated backend observation",
        "incarnation",
        _observation(backend_incarnation={
            "backend_url": "http://127.0.0.1:13309/v1",
            "pid": 4444,
            "launch_command": FIXED_LAUNCH + ["--prio", "high"],
            "launch_fingerprint": FIXED_FINGERPRINT,
        }), _client(), _policy())


def test_unqualified_opencode_version_is_rejected():
    _expect_failure(
        "qualification flag false",
        "qualified",
        _observation(), _client(qualified=False), _policy())


def test_qualified_version_is_trusted_not_whitelisted():
    # The pure function trusts the caller's qualification flag; it keeps no
    # private whitelist of version strings. A qualified version it has not
    # seen before is recorded as given.
    record = effective_inference_capacity(
        _observation(), _client(version="1.18.31"), _policy(), NOW)
    assert record["opencode_version"] == "1.18.31"
    assert record["derived_from"].endswith("opencode:1.18.31")


def test_reserve_above_client_ceiling_clamps_output():
    # The policy reserve is one of the ceilings that bound the effective
    # output (the smallest of the qualified ceiling, any observed backend
    # ceiling, and the reserve). When the reserve exceeds the client ceiling
    # the client ceiling binds: the output is clamped, not rejected, because
    # a smaller output is strictly safer for rollover room.
    record = effective_inference_capacity(
        _observation(), _client(maximum_output_tokens=20000), _policy(), NOW)
    assert record["effective_output_tokens"] == 20000
    assert record["opencode_output_tokens"] == 20000
    assert record["output_reserve_tokens"] == 30000


def test_prompt_plus_output_overflow_is_rejected():
    _expect_failure(
        "prompt plus reserved output does not fit the effective context",
        "fit",
        _observation(prompt_estimate_tokens=4000), _client(), _policy())


def test_stale_or_unknown_time_is_rejected():
    _expect_failure(
        "observation older than the freshness window",
        "stale",
        _observation(), _client(), _policy(), now=OBSERVED_AT + 301)
    _expect_failure(
        "observed in the future",
        "future",
        _observation(observed_at=NOW + 1), _client(), _policy())
    _expect_failure(
        "non-numeric now",
        "now",
        _observation(), _client(), _policy(), now="soon")


def test_absent_or_nonpositive_facts_are_rejected():
    _expect_failure(
        "zero output reserve",
        "output_reserve_tokens",
        _observation(), _client(), _policy(output_reserve_tokens=0))
    _expect_failure(
        "zero client ceiling",
        "maximum_output_tokens",
        _observation(), _client(maximum_output_tokens=0), _policy())
    _expect_failure(
        "absent evidence reference",
        "evidence",
        _observation(evidence=""), _client(), _policy())
    _expect_failure(
        "absent observation time",
        "observed_at",
        _observation(observed_at=None), _client(), _policy())
    _expect_failure(
        "negative prompt estimate",
        "prompt_estimate_tokens",
        _observation(prompt_estimate_tokens=-1), _client(), _policy())


def test_booleans_are_not_integers():
    _expect_failure(
        "boolean output reserve",
        "output_reserve_tokens",
        _observation(), _client(), _policy(output_reserve_tokens=True))
    _expect_failure(
        "boolean prompt estimate",
        "prompt_estimate_tokens",
        _observation(prompt_estimate_tokens=True), _client(), _policy())
    _expect_failure(
        "boolean rollover fraction",
        "rollover_fraction",
        _observation(), _client(), _policy(rollover_fraction=True))
    _expect_failure(
        "boolean pid",
        "pid",
        _observation(backend_incarnation={
            "backend_url": "http://127.0.0.1:13307/v1",
            "pid": True,
            "launch_command": list(FIXED_LAUNCH),
            "launch_fingerprint": FIXED_FINGERPRINT,
        }), _client(), _policy())


def test_unknown_context_mode_is_rejected():
    layout = dict(FIXED_LAYOUT, context_mode="elastic")
    _expect_failure(
        "unknown context mode",
        "context_mode",
        _observation(layout=layout), _client(), _policy())


def test_contradictory_layout_is_rejected():
    _expect_failure(
        "fixed pool not divisible by the slot count",
        "layout",
        _observation(layout={
            "context_mode": "fixed",
            "backend_context_tokens": 131072,
            "parallel_sequences": 3,
            "context_tokens_per_sequence": 43690,
            "preallocated_context_tokens": 131072,
        }), _client(), _policy())
    _expect_failure(
        "shared per-slot cap above the pool",
        "layout",
        _observation(layout={
            "context_mode": "shared",
            "backend_context_tokens": 262144,
            "parallel_sequences": 8,
            "context_tokens_per_sequence": 262145,
            "preallocated_context_tokens": 262144,
        }), _client(), _policy())
    _expect_failure(
        "layout preallocation disagrees with the pool",
        "layout",
        _observation(layout=dict(FIXED_LAYOUT,
                                 preallocated_context_tokens=65536)),
        _client(), _policy())


def test_rollover_policy_out_of_range_is_rejected():
    for fraction in (0, 1, -0.25, 1.5):
        _expect_failure(
            f"rollover fraction {fraction}",
            "rollover_fraction",
            _observation(), _client(), _policy(rollover_fraction=fraction))
    record = effective_inference_capacity(
        _observation(), _client(), _policy(rollover_fraction=0.00001), NOW)
    assert record["rollover_threshold_tokens"] < _observation()["prompt_estimate_tokens"]



def test_unknown_authority_keys_are_rejected():
    _expect_failure(
        "unknown observation key",
        "unknown",
        _observation(extra="fact"), _client(), _policy())
    _expect_failure(
        "unknown client key",
        "unknown",
        _observation(), _client(extra="cap"), _policy())
    _expect_failure(
        "unknown policy key",
        "unknown",
        _observation(), _client(), _policy(extra="reserve"))
    _expect_failure(
        "unknown incarnation key",
        "unknown",
        _observation(backend_incarnation={
            "backend_url": "http://127.0.0.1:13307/v1",
            "pid": 4242,
            "launch_command": list(FIXED_LAUNCH),
            "launch_fingerprint": FIXED_FINGERPRINT,
            "extra": "fact",
        }), _client(), _policy())


def test_missing_authority_keys_are_rejected():
    for key in ("selected_model_id", "observed_model_id", "backend_incarnation",
                "layout", "observed_at", "evidence", "prompt_estimate_tokens",
                "backend_output_ceiling"):
        observation = _observation()
        del observation[key]
        _expect_failure(
            f"missing observation key {key}",
            key,
            observation, _client(), _policy())
    for key in ("version", "qualified", "maximum_output_tokens"):
        client = _client()
        del client[key]
        _expect_failure(
            f"missing client key {key}",
            key,
            _observation(), client, _policy())
    for key in ("output_reserve_tokens", "rollover_fraction", "max_age_seconds"):
        policy = _policy()
        del policy[key]
        _expect_failure(
            f"missing policy key {key}",
            key,
            _observation(), _client(), policy)
    for key in ("backend_url", "pid", "launch_command", "launch_fingerprint"):
        incarnation = _observation()["backend_incarnation"]
        del incarnation[key]
        _expect_failure(
            f"missing incarnation key {key}",
            key,
            _observation(backend_incarnation=incarnation), _client(), _policy())


def test_non_dictionary_arguments_are_rejected():
    for label, arguments in (
        ("observation", (None, CLIENT, POLICY, NOW)),
        ("client", (OBSERVATION, "1.18.30", POLICY, NOW)),
        ("policy", (OBSERVATION, CLIENT, None, NOW)),
    ):
        _expect_failure(f"non-dictionary {label}", "dictionary", *arguments)


def test_non_positive_backend_output_ceiling_is_rejected():
    _expect_failure(
        "zero backend output ceiling",
        "backend_output_ceiling",
        _observation(backend_output_ceiling=0), _client(), _policy())
    _expect_failure(
        "boolean backend output ceiling",
        "backend_output_ceiling",
        _observation(backend_output_ceiling=True), _client(), _policy())


def test_backend_output_ceiling_binds_effective_output():
    record = effective_inference_capacity(
        _observation(backend_output_ceiling=28000), _client(), _policy(), NOW)
    assert record["effective_output_tokens"] == 28000
    assert record["opencode_output_tokens"] == 28000


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(
        unittest.FunctionTestCase(function) for function in functions)
