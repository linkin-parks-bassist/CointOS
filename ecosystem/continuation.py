"""Explicit context-continuation state machine for task execution.

The context-run state lives on the job record as plain data:
`context_state` and `context_generation`. The executor is the adapter: it
parses durable backend session events, calls these transitions, and
persists their fragments. The backend never decides when a context ends;
the lease budget does. `job_id` and `agent_generation` survive context and
model changes, process restarts, and `paused_for_resources`; only
`context_generation` advances across continuations, and only a genuinely
new attempt increments `agent_generation`. Evidence is carried by
reference; a missing semantic handoff remains visibly continuable.
"""


def _positive_integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _non_negative_integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _require_id(job):
    if not isinstance(job, dict) or not isinstance(job.get("id"), str) or not job["id"]:
        raise ValueError("continuation requires a job with a non-empty string id")
    return job


def _current_state(job):
    state = job.get("context_state")
    if state is None:
        return "running"
    if state not in ("running", "handoff_requested", "handoff_durable",
                     "continuation_ready", "paused_for_resources"):
        raise ValueError(f"unknown context state {state!r}")
    return state


def observe_context_usage(adapter_event: dict, lease: dict) -> dict:
    """Normalize one backend usage event against the lease context total.

    Overflow (usage_fraction > 1.0) is a fact about the lease, not an
    error: a context may run past its nominal budget until stopped.
    """
    if not isinstance(adapter_event, dict) or not isinstance(lease, dict):
        raise ValueError("observe_context_usage requires event and lease dictionaries")
    total = adapter_event.get("total_tokens")
    if not _non_negative_integer(total):
        raise ValueError("adapter event lacks a non-negative integer total_tokens")
    context = lease.get("context_tokens")
    if not _positive_integer(context):
        raise ValueError("lease lacks a positive integer context_tokens")
    return {
        "session": adapter_event.get("session"),
        "total_tokens": total,
        "context_tokens": context,
        "usage_fraction": total / context,
    }


def context_transition(job: dict, usage: dict, rollover_fraction: float) -> dict:
    """Advance the context state from an observed usage.

    `running` crosses into `handoff_requested` at the rollover fraction,
    which must precede the backend limit. A requested context stays
    requested no matter how far it overflows: context overflow is never
    terminal.
    """
    _require_id(job)
    if not isinstance(usage, dict):
        raise ValueError("context_transition requires a normalized usage record")
    total = usage.get("total_tokens")
    context = usage.get("context_tokens")
    fraction = usage.get("usage_fraction")
    if (not _non_negative_integer(total) or not _positive_integer(context)
            or isinstance(fraction, bool) or not isinstance(fraction, (int, float))):
        raise ValueError("context_transition requires a normalized usage record")
    if (isinstance(rollover_fraction, bool)
            or not isinstance(rollover_fraction, (int, float))
            or not 0 < rollover_fraction < 1):
        raise ValueError("rollover fraction must precede the backend limit (0 < f < 1)")
    state = _current_state(job)
    if state not in ("running", "handoff_requested"):
        raise ValueError(f"usage cannot be observed in context state {state!r}")
    if state == "running" and fraction >= rollover_fraction:
        state = "handoff_requested"
    return {
        "context_state": state,
        "context_usage": usage,
        "context_overflow": fraction >= 1.0,
    }


def attest_handoff(job: dict, handoff: dict) -> dict:
    """Attest that a durable semantic handoff now exists for this context."""
    _require_id(job)
    state = _current_state(job)
    if state not in ("running", "handoff_requested"):
        raise ValueError(f"a handoff cannot be attested in context state {state!r}")
    if not isinstance(handoff, dict):
        raise ValueError("attest_handoff requires a handoff record")
    if not isinstance(handoff.get("summary"), str) or not handoff["summary"]:
        raise ValueError("an attested handoff needs a non-empty summary")
    if not _non_negative_integer(handoff.get("token_count")):
        raise ValueError("an attested handoff needs a non-negative integer token_count")
    return {"context_state": "handoff_durable", "handoff": handoff}


def handoff_budget(destination_lease: dict) -> dict:
    """Reserve the destination prompt/output/tool/handoff partition.

    The partition must fit inside the destination context; a route that
    cannot hold its reserves is infeasible and is rejected, never trimmed.
    """
    if not isinstance(destination_lease, dict):
        raise ValueError("handoff_budget requires a destination lease dictionary")
    budget = {}
    for name in ("context_tokens", "prompt_tokens", "handoff_tokens",
                 "tool_tokens", "max_output_tokens"):
        value = destination_lease.get(name)
        if not _positive_integer(value):
            raise ValueError(f"destination lease lacks a positive integer {name}")
        budget[name] = value
    partition = (budget["prompt_tokens"] + budget["handoff_tokens"]
                 + budget["tool_tokens"] + budget["max_output_tokens"])
    if partition > budget["context_tokens"]:
        raise ValueError(
            f"destination partition {partition} exceeds context "
            f"{budget['context_tokens']}")
    return budget


def prepare_continuation(job: dict, handoff: dict | None, artifacts: dict,
                         destination_lease: dict) -> dict:
    """Build the next-context record against an admitted destination lease.

    Task identity (`id`, `agent_generation`) is preserved; only the
    context generation advances. A null handoff stays visibly continuable
    (`handoff_missing`), never a failure; an over-budget handoff fails
    explicitly so the writer resizes it.
    """
    _require_id(job)
    generation = job.get("agent_generation")
    if not _positive_integer(generation):
        raise ValueError("continuation requires an A1 agent_generation")
    context_generation = job.get("context_generation", 1)
    if not _positive_integer(context_generation):
        raise ValueError("context_generation must be a positive integer")
    state = _current_state(job)
    if state == "continuation_ready":
        raise ValueError("context already continued; a double continuation is a bug")
    if not isinstance(destination_lease, dict):
        raise ValueError("prepare_continuation requires a destination lease dictionary")
    model_id = destination_lease.get("model_id")
    if not isinstance(model_id, str) or not model_id:
        raise ValueError("destination lease needs a non-empty model_id")
    budget = handoff_budget(destination_lease)
    if handoff is None:
        handoff_record, handoff_missing = None, True
    elif not isinstance(handoff, dict):
        raise ValueError("handoff must be a record or null")
    else:
        token_count = handoff.get("token_count")
        if not _non_negative_integer(token_count):
            raise ValueError("handoff needs a non-negative integer token_count")
        if token_count > budget["handoff_tokens"]:
            raise ValueError(
                f"handoff of {token_count} tokens exceeds the destination handoff "
                f"budget of {budget['handoff_tokens']}")
        handoff_record, handoff_missing = handoff, False
    if not isinstance(artifacts, dict):
        raise ValueError("artifacts must be a dictionary")
    evidence = artifacts.get("evidence_paths", [])
    if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence):
        raise ValueError("evidence_paths must be a list of reference paths")
    return {
        "id": job["id"],
        "agent_generation": generation,
        "context_generation": context_generation + 1,
        "context_state": "continuation_ready",
        "model_id": model_id,
        "destination_budget": budget,
        "handoff": handoff_record,
        "handoff_missing": handoff_missing,
        "evidence": list(evidence),
    }


def new_attempt(job: dict) -> dict:
    """A genuinely new attempt of the same task increments agent generation."""
    _require_id(job)
    generation = job.get("agent_generation")
    if not _positive_integer(generation):
        raise ValueError("new_attempt requires an A1 agent_generation")
    attempts = job.get("attempts")
    if not _non_negative_integer(attempts):
        raise ValueError("new_attempt requires a non-negative integer attempts counter")
    return {
        "id": job["id"],
        "agent_generation": generation + 1,
        "attempts": attempts + 1,
        "context_generation": 1,
        "context_state": "running",
        "logical_run_state": "active",
    }
