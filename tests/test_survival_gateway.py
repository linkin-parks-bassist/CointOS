import json
import tempfile
import unittest
from pathlib import Path

from survival import gateway, records, protocol


def with_survival_root(function):
    def run():
        with tempfile.TemporaryDirectory() as temporary:
            function(Path(temporary))

    run.__name__ = function.__name__
    return run


def telegram_update(update_id, user_id, text, chat_id=None):
    return {
        "update_id": update_id,
        "message": {
            "from": {"id": user_id},
            "chat": {"id": user_id if chat_id is None else chat_id},
            "text": text,
        },
    }


def fail_if_called(*args, **kwargs):
    raise RuntimeError("this callback must not be called")


sent_messages = []
captured_commands = []


def capture_send(chat_id, text):
    sent_messages.append((chat_id, text))


def reset_captures():
    global sent_messages, captured_commands
    sent_messages = []
    captured_commands = []


def write_old_pending_message(root, update_id):
    inbox_path = root / "inbox" / f"telegram-{update_id}.json"
    inbox_path.parent.mkdir(parents=True, exist_ok=True)
    records.atomic_json(inbox_path, {
        "schema_version": 1,
        "id": f"telegram-{update_id}",
        "telegram_update_id": update_id,
        "telegram_user_id": 42,
        "chat_id": 42,
        "text": "old message",
        "received_at": "2026-09-03T00:00:00+00:00",
        "egress_state": "ready",
    })


def test_command_is_acknowledged_and_sent_to_guardian():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        update = telegram_update(7, 42, "RESET")
        result = gateway.handle_update(
            update, {42}, root,
            send=capture_send,
            send_command=captured_commands.append,
        )
        assert result["kind"] == "command"
        assert captured_commands[0]["command"] == "reset"
        assert sent_messages == [(42, "Reset accepted. I am staying online while the agent system restarts.")]


def test_ordinary_message_is_spooled_without_model_call():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        update = telegram_update(8, 42, "how is scheduler?")
        result = gateway.handle_update(
            update, {42}, root,
            send=fail_if_called,
            send_command=fail_if_called,
        )
        assert result["kind"] == "ordinary"
        inbox_path = root / "inbox" / "telegram-8.json"
        assert inbox_path.exists()
        stored = json.loads(inbox_path.read_text(encoding="utf-8"))
        assert stored["text"] == "how is scheduler?"
        assert stored["egress_state"] == "ready"


def test_denied_user_creates_audit_without_message_text():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        update = telegram_update(9, 7, "RESTART")
        result = gateway.handle_update(
            update, {42}, root,
            send=fail_if_called,
            send_command=fail_if_called,
        )
        assert result["kind"] == "denied"
        audit_path = root / "inbox" / "denied-7.json"
        assert audit_path.exists()
        stored = json.loads(audit_path.read_text(encoding="utf-8"))
        assert stored["egress_state"] == "denied"
        assert "text" not in stored


def test_due_message_gets_honest_degraded_reply():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        write_old_pending_message(root, 8)
        count = gateway.send_due_degraded_responses(
            root, send=capture_send, now=10.0,
        )
        assert count == 1
        assert sent_messages == [(42, "I am degraded. I will reply properly after restart.")]
        inbox_path = root / "inbox" / "telegram-8.json"
        stored = json.loads(inbox_path.read_text(encoding="utf-8"))
        assert stored["egress_state"] == "delivered"


def test_no_due_messages_returns_zero():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        count = gateway.send_due_degraded_responses(
            root, send=capture_send, now=10.0,
        )
        assert count == 0
        assert sent_messages == []


def test_critical_outbox_is_sent_and_marked():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        outbox_path = root / "outbox" / "critical"
        outbox_path.mkdir(parents=True, exist_ok=True)
        records.atomic_json(outbox_path / "telegram-10.json", {
            "schema_version": 1,
            "id": "telegram-10",
            "telegram_update_id": 10,
            "telegram_user_id": 42,
            "chat_id": 42,
            "text": "critical message",
            "received_at": "2026-09-04T00:00:00+00:00",
            "egress_state": "sending",
        })
        count = gateway.drain_critical_outbox(root, send=capture_send)
        assert count == 1
        assert sent_messages == [(42, "critical message")]
        stored = json.loads((outbox_path / "telegram-10.json").read_text(encoding="utf-8"))
        assert stored["egress_state"] == "delivered"


def test_empty_outbox_returns_zero():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        outbox_path = root / "outbox" / "critical"
        outbox_path.mkdir(parents=True, exist_ok=True)
        count = gateway.drain_critical_outbox(root, send=capture_send)
        assert count == 0


def test_heartbeat_is_written():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        gateway.mark_gateway_heartbeat(root, 100.5)
        hb_path = root / "heartbeat.json"
        assert hb_path.exists()
        stored = json.loads(hb_path.read_text(encoding="utf-8"))
        assert stored["gateway_heartbeat"] == 100.5


def test_acknowledgement_returns_expected_text():
    assert gateway.acknowledgement("restart") == "Restart accepted. I am staying online while the agent system restarts."
    assert gateway.acknowledgement("reset") == "Reset accepted. I am staying online while the agent system restarts."


def test_command_record_has_strict_fields():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        accepted = records.accept_update(root, telegram_update(91, 42, "RESTART"), {42})
        cmd = gateway.command_record(accepted, "restart")
        assert set(cmd) == {"schema_version", "request_id", "telegram_update_id",
                            "telegram_user_id", "command", "received_at"}
        assert cmd["command"] == "restart"
        assert cmd["request_id"] == "telegram-91"


def test_ordinary_update_with_different_chat_id():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        update = telegram_update(15, 42, "hello", chat_id=99)
        result = gateway.handle_update(
            update, {42}, root,
            send=fail_if_called,
            send_command=fail_if_called,
        )
        assert result["kind"] == "ordinary"
        inbox_path = root / "inbox" / "telegram-15.json"
        stored = json.loads(inbox_path.read_text(encoding="utf-8"))
        assert stored["chat_id"] == 99


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
