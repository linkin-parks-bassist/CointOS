import unittest

from ecosystem.continuation import (
    attest_handoff,
    context_transition,
    handoff_budget,
    new_attempt,
    observe_context_usage,
    prepare_continuation,
)

JOB = {"id": "task-one", "agent_generation": 7, "context_generation": 2}
DESTINATION = {"model_id": "smaller", "context_tokens": 16384,
               "prompt_tokens": 8000, "handoff_tokens": 2000,
               "tool_tokens": 2000, "max_output_tokens": 4384}


def test_task_identity_survives_smaller_destination():
    job = {"id": "task-one", "agent_generation": 7, "context_generation": 2}
    destination = {"model_id": "smaller", "context_tokens": 16384,
                   "prompt_tokens": 8000, "handoff_tokens": 2000,
                   "tool_tokens": 2000, "max_output_tokens": 4384}
    result = prepare_continuation(
        job, {"summary": "bounded", "token_count": 1800},
        {"evidence_paths": ["logs/task-one.context-2.jsonl"]}, destination)
    assert result["id"] == "task-one" and result["agent_generation"] == 7
    assert result["context_generation"] == 3 and result["model_id"] == "smaller"


def test_rollover_precedes_backend_limit():
    usage = observe_context_usage({"total_tokens": 75, "session": "ses_1"},
                                  {"context_tokens": 100})
    transition = context_transition(dict(JOB), usage, 0.75)
    assert transition["context_state"] == "handoff_requested"
    assert transition["context_usage"]["usage_fraction"] == 0.75
    below = observe_context_usage({"total_tokens": 74}, {"context_tokens": 100})
    assert context_transition(dict(JOB), below, 0.75)["context_state"] == "running"
    try:
        context_transition(dict(JOB), usage, 1.0)
        raise AssertionError("a rollover fraction of 1.0 must be rejected")
    except ValueError:
        pass
    try:
        context_transition(dict(JOB), usage, 0.0)
        raise AssertionError("a rollover fraction of 0.0 must be rejected")
    except ValueError:
        pass


def test_handoff_fits_destination_prompt_budget():
    budget = handoff_budget(DESTINATION)
    assert budget["handoff_tokens"] == 2000
    assert budget["prompt_tokens"] == 8000
    fits = prepare_continuation(dict(JOB), {"summary": "s", "token_count": 2000},
                                {}, DESTINATION)
    assert fits["handoff_missing"] is False
    try:
        prepare_continuation(dict(JOB), {"summary": "s", "token_count": 2001},
                             {}, DESTINATION)
        raise AssertionError("an over-budget handoff must fail explicitly")
    except ValueError:
        pass
    infeasible = dict(DESTINATION, max_output_tokens=4385)
    try:
        handoff_budget(infeasible)
        raise AssertionError("a destination whose partition exceeds its context must fail")
    except ValueError:
        pass


def test_model_switch_preserves_agent_generation():
    result = prepare_continuation(dict(JOB, context_state="running"), None,
                                  {}, DESTINATION)
    assert result["id"] == "task-one"
    assert result["agent_generation"] == 7
    assert result["context_generation"] == 3
    assert result["model_id"] == "smaller"
    assert result["context_state"] == "continuation_ready"


def test_process_restart_preserves_agent_generation():
    job = dict(JOB, context_state="running")
    usage = observe_context_usage({"total_tokens": 10}, {"context_tokens": 100})
    fragment = context_transition(job, usage, 0.75)
    assert "agent_generation" not in fragment
    assert "context_generation" not in fragment
    restarted = {**job, **fragment}
    assert restarted["agent_generation"] == 7
    assert restarted["context_generation"] == 2
    assert restarted["context_state"] == "running"


def test_new_attempt_increments_agent_generation():
    terminal = dict(JOB, context_state="running",
                    logical_run_state="terminal", state="checkpoint_required")
    attempt = new_attempt(terminal)
    assert attempt["id"] == "task-one"
    assert attempt["agent_generation"] == 8
    assert attempt["context_generation"] == 1
    assert attempt["context_state"] == "running"
    assert attempt["logical_run_state"] == "active"


def test_paused_for_resources_remains_addressable_without_lease():
    paused = dict(JOB, context_state="paused_for_resources")
    assert paused["agent_generation"] == 7 and paused["context_generation"] == 2
    result = prepare_continuation(paused, {"summary": "s", "token_count": 100},
                                  {}, DESTINATION)
    assert result["agent_generation"] == 7
    assert result["context_generation"] == 3
    assert result["context_state"] == "continuation_ready"
    usage = observe_context_usage({"total_tokens": 1}, {"context_tokens": 100})
    try:
        context_transition(paused, usage, 0.75)
        raise AssertionError("usage cannot be observed while paused without a lease")
    except ValueError:
        pass


def test_missing_handoff_is_visible_and_continues():
    result = prepare_continuation(
        dict(JOB, context_state="handoff_requested"), None,
        {"evidence_paths": ["logs/task-one.context-1.jsonl"]}, DESTINATION)
    assert result["context_state"] == "continuation_ready"
    assert result["handoff"] is None
    assert result["handoff_missing"] is True
    assert result["agent_generation"] == 7
    assert result["context_generation"] == 3


def test_context_overflow_is_never_terminal():
    usage = observe_context_usage({"total_tokens": 137}, {"context_tokens": 100})
    assert usage["usage_fraction"] == 1.37
    job = dict(JOB, context_state="running")
    transition = context_transition(job, usage, 0.75)
    assert transition["context_state"] == "handoff_requested"
    assert transition["context_overflow"] is True
    again = context_transition(dict(job, context_state="handoff_requested"),
                               usage, 0.75)
    assert again["context_state"] == "handoff_requested"
    result = prepare_continuation(dict(job, context_state="handoff_requested"),
                                  {"summary": "s", "token_count": 50}, {}, DESTINATION)
    assert result["context_state"] == "continuation_ready"


def test_context_state_machine_advances_explicitly():
    job = {"id": "t", "agent_generation": 1, "context_generation": 1}
    usage = observe_context_usage({"total_tokens": 80}, {"context_tokens": 100})
    requested = context_transition(job, usage, 0.75)
    assert requested["context_state"] == "handoff_requested"
    advanced = {**job, **requested}
    handoff = {"path": "state/jobs/t.handoff.md",
               "summary": "completed work so far", "token_count": 120}
    durable = attest_handoff(advanced, handoff)
    assert durable["context_state"] == "handoff_durable"
    advanced = {**advanced, **durable}
    ready = prepare_continuation(advanced, advanced["handoff"],
                                 {"evidence_paths": []}, DESTINATION)
    assert ready["context_state"] == "continuation_ready"
    assert ready["context_generation"] == 2
    try:
        prepare_continuation({**advanced, **ready}, advanced["handoff"], {}, DESTINATION)
        raise AssertionError("a double continuation must fail explicitly")
    except ValueError:
        pass
    try:
        attest_handoff({**advanced, **durable}, handoff)
        raise AssertionError("a double handoff attestation must fail explicitly")
    except ValueError:
        pass


def load_tests(_loader, _tests, _pattern):
    return unittest.TestSuite([
        unittest.FunctionTestCase(test_task_identity_survives_smaller_destination),
        unittest.FunctionTestCase(test_rollover_precedes_backend_limit),
        unittest.FunctionTestCase(test_handoff_fits_destination_prompt_budget),
        unittest.FunctionTestCase(test_model_switch_preserves_agent_generation),
        unittest.FunctionTestCase(test_process_restart_preserves_agent_generation),
        unittest.FunctionTestCase(test_new_attempt_increments_agent_generation),
        unittest.FunctionTestCase(test_paused_for_resources_remains_addressable_without_lease),
        unittest.FunctionTestCase(test_missing_handoff_is_visible_and_continues),
        unittest.FunctionTestCase(test_context_overflow_is_never_terminal),
        unittest.FunctionTestCase(test_context_state_machine_advances_explicitly),
    ])
