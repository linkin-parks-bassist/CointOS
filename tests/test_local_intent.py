import unittest

from ecosystem.control_agent import respond
from ecosystem.presentation import sanitize_notification
from ecosystem.telegram import FAST_SYSTEM, generate_first_response, generate_front_decision


def tool_call(name, arguments="{}", identifier="call-one"):
    return {"id": identifier, "type": "function",
            "function": {"name": name, "arguments": arguments}}


def test_control_agent_uses_tool_then_publishes_material_followup():
    answers = iter([
        {"content": None, "tool_calls": [tool_call("inspect_status")]},
        {"content": None, "tool_calls": [tool_call(
            "publish_followup", '{"message":"Qwen is loaded."}', "call-two")]},
    ])
    calls = []
    outcome = respond("Is Qwen loaded?", [], "I’ll check the exact state.", {"models": []},
                      lambda name, arguments: calls.append((name, arguments)) or {"ok": True},
                      infer=lambda **_arguments: next(answers))
    assert outcome == {"followup": "Qwen is loaded."}
    assert calls == [("inspect_status", {})]


def test_control_agent_can_finish_without_duplicate_reply():
    outcome = respond("nice", [], "Ha, yep.", {}, lambda *_arguments: {},
                      infer=lambda **_arguments: {
                          "content": None, "tool_calls": [tool_call("finish_silently")]
                      })
    assert outcome == {"followup": None}


def test_control_agent_cannot_silently_drop_promised_reasoning_result():
    answers = iter([
        {"content": None, "tool_calls": [tool_call("finish_silently")]},
        {"content": None, "tool_calls": [tool_call(
            "publish_followup", '{"message":"Here is the proof."}', "call-two")]},
    ])
    captured = []

    def infer(**arguments):
        captured.append(arguments["messages"])
        return next(answers)

    outcome = respond(
        "Prove the Sylow theorems", [],
        "I'll need to check the exact reasoning steps to provide a rigorous proof.",
        {}, lambda *_arguments: {}, infer=infer,
    )

    assert outcome == {"followup": "Here is the proof."}
    assert any(
        item.get("role") == "user" and "only promised later work" in item.get("content", "")
        for item in captured[-1]
    )


def test_control_agent_queue_schema_and_handler_allow_omitted_role():
    answers = iter([
        {"content": None, "tool_calls": [tool_call(
            "queue_task", '{"task":"inspect","agent_name":"Noether"}')]},
        {"content": None, "tool_calls": [tool_call("finish_silently", identifier="call-two")]},
    ])
    calls = []

    def infer(**arguments):
        queue_tool = next(tool for tool in arguments["tools"]
                          if tool["function"]["name"] == "queue_task")
        parameters = queue_tool["function"]["parameters"]
        assert "role" not in parameters["required"]
        assert parameters["properties"]["role"]["type"] == ["string", "null"]
        return next(answers)

    result = respond("inspect it", [], "I’ll inspect it.", {},
                     lambda name, arguments: calls.append((name, arguments)) or {"ok": True},
                     infer=infer)
    assert result == {"followup": None}
    assert calls == [("queue_task", {"task": "inspect", "agent_name": "Noether"})]


def test_fast_response_is_small_and_forbids_action_claims():
    captured = {}
    def infer(**arguments):
        captured.update(arguments)
        return {"content": '{"response":"Yep — that distinction matters.","deep_required":false}'}
    response = generate_first_response([{"role": "user", "content": "Don't claim it started."}], infer=infer)
    assert response == "Yep — that distinction matters."
    assert captured["max_tokens"] == 512
    assert captured["timeout"] == 20
    assert "without claiming that the requested action has already" in FAST_SYSTEM
    assert "started" in FAST_SYSTEM
    assert "Never say the system cannot act" in FAST_SYSTEM
    assert "do not mention stages" in FAST_SYSTEM
    assert "never supply a candidate fact" in FAST_SYSTEM
    assert len(captured["messages"]) == 2


def test_fast_response_receives_the_durable_control_plane_identity():
    captured = {}

    def infer(**arguments):
        captured.update(arguments)
        return {"content": '{"response":"Yep.","deep_required":false}'}

    generate_first_response([{"role": "user", "content": "Who are you?"}], infer=infer)
    system = captured["messages"][0]["content"]
    assert "David's private Telegram-facing control plane" in system
    assert "You are not a generic internet chatbot" in system
    assert "Do not end messages with generic opt-in chatbot questions" in system
    assert "Mandatory knowledge-tree bootstrap" not in system


def test_fast_response_removes_generic_chatbot_followup_tail():
    response = generate_first_response(
        [{"role": "user", "content": "yay"}],
        infer=lambda **_arguments: {
            "content": '{"response":"Excellent, glad that is sorted! Would you like me to help with anything else?","deep_required":false}'
        },
    )
    assert response == "Excellent, glad that is sorted!"


def test_fast_front_can_choose_intentional_silence_without_deep_work():
    decision = generate_front_decision(
        [{"role": "user", "content": "yippee"}],
        infer=lambda **_arguments: {"content": '{"response":null,"deep_required":false}'},
    )
    assert decision == {"response": None, "deep_required": False}


def test_removes_generic_chatbot_tail():
    raw = "Cyrus updated the system map. Want to dive into it or should we chat about something else?"
    assert sanitize_notification(raw) == "Cyrus updated the system map."


def load_tests(_loader, _tests, _pattern):
    functions = [
        test_control_agent_uses_tool_then_publishes_material_followup,
        test_control_agent_can_finish_without_duplicate_reply,
        test_control_agent_cannot_silently_drop_promised_reasoning_result,
        test_control_agent_queue_schema_and_handler_allow_omitted_role,
        test_fast_response_is_small_and_forbids_action_claims,
        test_fast_response_receives_the_durable_control_plane_identity,
        test_fast_response_removes_generic_chatbot_followup_tail,
        test_fast_front_can_choose_intentional_silence_without_deep_work,
        test_removes_generic_chatbot_tail,
    ]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
