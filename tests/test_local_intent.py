import unittest

from ecosystem.control_agent import respond
from ecosystem.presentation import sanitize_notification
from ecosystem.telegram import FAST_SYSTEM, generate_first_response


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
        return {"content": "Yep — that distinction matters."}
    response = generate_first_response([{"role": "user", "content": "Don't claim it started."}], infer=infer)
    assert response == "Yep — that distinction matters."
    assert captured["max_tokens"] == 96
    assert captured["timeout"] == 20
    assert "without claiming that the requested action has already" in FAST_SYSTEM
    assert "started" in FAST_SYSTEM
    assert "Never say the system cannot act" in FAST_SYSTEM
    assert "do not mention stages" in FAST_SYSTEM
    assert "never supply a candidate fact" in FAST_SYSTEM
    assert len(captured["messages"]) == 2


def test_removes_generic_chatbot_tail():
    raw = "Cyrus updated the system map. Want to dive into it or should we chat about something else?"
    assert sanitize_notification(raw) == "Cyrus updated the system map."


def load_tests(_loader, _tests, _pattern):
    functions = [
        test_control_agent_uses_tool_then_publishes_material_followup,
        test_control_agent_can_finish_without_duplicate_reply,
        test_control_agent_queue_schema_and_handler_allow_omitted_role,
        test_fast_response_is_small_and_forbids_action_claims,
        test_removes_generic_chatbot_tail,
    ]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
