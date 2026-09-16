import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ecosystem import cli, conversation, notifier, outbox
from ecosystem.telegram import accept_update


def with_root(function):
    def run():
        with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
            cli.initialize()
            function(Path(temporary))
    run.__name__ = function.__name__
    return run


def update(identifier=91, text="is it finished?"):
    return {"update_id": identifier, "message": {
        "from": {"id": 42}, "chat": {"id": 42}, "text": text,
    }}


@with_root
def test_terminal_result_uses_notifier_without_blocking_telegram_ingress(root):
    output = root / "logs/result.log"
    output.parent.mkdir(exist_ok=True)
    output.write_text("verified result", encoding="utf-8")
    cli.atomic_json(root / "state/jobs/task-finished.json", {
        "id": "task-finished",
        "kind": "agent-task",
        "state": "completed",
        "agent_name": "Noether",
        "output": "logs/result.log",
        "verification_summary": "all checks passed",
    })
    notification_id = outbox.enqueue(
        42, depends_on="task-finished", result_of="task-finished"
    )
    sent = []
    accept_update("token", update(), {42},
                  send=lambda token, user_id, message: sent.append((token, user_id, message)),
                  infer=lambda **_arguments: {"content":
                      '{"response":"I’ll check the record.","deep_required":true}'})
    waiting = json.loads((root / f"state/jobs/{notification_id}.json").read_text())
    assert waiting["state"] == "waiting"
    assert sent == [("token", 42, "I’ll check the record.")]

    run_once = getattr(notifier, "run_once", None)
    assert run_once is not None
    assert run_once(
        token="token",
        send=lambda token, user_id, message: sent.append((token, user_id, message)),
        present=lambda raw, _history: "Presented: " + raw,
    ) == 1
    assert len(sent) == 2
    assert "Noether's work passed an independent check" in sent[1][2]
    assert "verified result" in sent[1][2]
    delivered = json.loads((root / f"state/jobs/{notification_id}.json").read_text())
    assert delivered["state"] == "delivered"
    assert conversation.recent(42)[-1]["content"] == sent[1][2]


@with_root
def test_external_send_failure_is_delivery_unknown(root):
    notification_id = outbox.enqueue(42, message="important result")

    def uncertain_send(_user_id, _message):
        raise TimeoutError("delivery outcome unknown")

    assert outbox.drain(uncertain_send) == 0
    saved = json.loads((root / f"state/jobs/{notification_id}.json").read_text())
    assert saved["state"] == "delivery_unknown"
    assert saved["attempts"] == 1
    assert outbox.drain(lambda *_arguments: None) == 0


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
