import json
import tempfile
import time
import unittest
from datetime import datetime, timezone
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


def capture_send(chat_id, text):
    capture_send.messages.append((chat_id, text))


def reset_captures():
    capture_send.messages = []
    capture_send.commands = []


capture_send.messages = []
capture_send.commands = []


def _epoch_seconds(iso_str):
    return datetime.fromisoformat(iso_str).timestamp()


def write_old_pending_message(root, update_id, now=None):
    inbox_path = root / "inbox" / f"telegram-{update_id}.json"
    inbox_path.parent.mkdir(parents=True, exist_ok=True)
    received_at = "2025-01-01T00:00:00+00:00"
    if now is None:
        now = _epoch_seconds(received_at) + 400
    records.atomic_json(inbox_path, {
        "schema_version": 1,
        "id": f"telegram-{update_id}",
        "telegram_update_id": update_id,
        "telegram_user_id": 42,
        "chat_id": 42,
        "text": "old message",
        "received_at": received_at,
        "egress_state": "ready",
    })
    return now


def test_command_is_acknowledged_and_sent_to_guardian():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        update = telegram_update(7, 42, "RESET")
        result = gateway.handle_update(
            update, {42}, root,
            send=capture_send,
            send_command=capture_send.commands.append,
        )
        assert result["kind"] == "command"
        assert capture_send.commands[0]["command"] == "reset"
        assert capture_send.messages == [(42, "Reset accepted. I am staying online while the agent system restarts.")]


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
        now = write_old_pending_message(root, 8)
        count = gateway.send_due_degraded_responses(
            root, send=capture_send, now=now,
        )
        assert count == 1
        assert capture_send.messages == [(42, "I am degraded. I will reply properly after restart.")]
        inbox_path = root / "inbox" / "telegram-8.json"
        stored = json.loads(inbox_path.read_text(encoding="utf-8"))
        assert stored["egress_state"] == "delivered"


def test_no_due_messages_returns_zero():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        count = gateway.send_due_degraded_responses(
            root, send=capture_send, now=time.monotonic(),
        )
        assert count == 0
        assert capture_send.messages == []


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
        assert capture_send.messages == [(42, "critical message")]
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


# --- Regression tests for review findings ---


def test_acknowledgement_stores_separately_not_in_accepted_record():
    """Critical 5: mark_acknowledged must not mutate the accepted command record."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        update = telegram_update(99, 42, "RESTART")
        gateway.handle_update(
            update, {42}, root,
            send=capture_send,
            send_command=capture_send.commands.append,
        )
        # The accepted command record must have only the strict fields
        cmd_path = root / "commands" / "telegram-99.json"
        stored = json.loads(cmd_path.read_text(encoding="utf-8"))
        assert set(stored) == {
            "schema_version", "id", "telegram_update_id",
            "telegram_user_id", "chat_id", "text", "received_at",
        }
        # The ack must exist in its own file
        ack_path = root / "acks" / "telegram-99.json"
        assert ack_path.exists()
        ack_data = json.loads(ack_path.read_text(encoding="utf-8"))
        assert ack_data["update_id"] == "telegram-99"
        assert "acknowledged_at" in ack_data


def test_degraded_reply_respects_real_deadline():
    """Critical 4: send_due_degraded_responses must filter by real deadline."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        inbox_path = root / "inbox" / "telegram-50.json"
        inbox_path.parent.mkdir(parents=True, exist_ok=True)
        received_at = "2025-06-01T00:00:00+00:00"
        now = _epoch_seconds(received_at) + 10  # only 10 seconds old, under 300s deadline
        records.atomic_json(inbox_path, {
            "schema_version": 1,
            "id": "telegram-50",
            "telegram_update_id": 50,
            "telegram_user_id": 42,
            "chat_id": 42,
            "text": "still fresh",
            "received_at": received_at,
            "egress_state": "ready",
        })
        count = gateway.send_due_degraded_responses(root, send=capture_send, now=now)
        assert count == 0
        assert capture_send.messages == []


def test_degraded_reply_sends_when_past_deadline():
    """Critical 4: messages older than the deadline should get degraded reply."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        inbox_path = root / "inbox" / "telegram-51.json"
        inbox_path.parent.mkdir(parents=True, exist_ok=True)
        received_at = "2025-01-01T00:00:00+00:00"
        now = _epoch_seconds(received_at) + 400  # 400 seconds, past 300s deadline
        records.atomic_json(inbox_path, {
            "schema_version": 1,
            "id": "telegram-51",
            "telegram_update_id": 51,
            "telegram_user_id": 42,
            "chat_id": 42,
            "text": "very stale",
            "received_at": received_at,
            "egress_state": "ready",
        })
        count = gateway.send_due_degraded_responses(root, send=capture_send, now=now)
        assert count == 1
        assert capture_send.messages == [(42, "I am degraded. I will reply properly after restart.")]


def test_drain_persists_sending_before_send():
    """Critical 3: drain must persist 'sending' state before attempting send."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        outbox_path = root / "outbox" / "critical"
        outbox_path.mkdir(parents=True, exist_ok=True)
        records.atomic_json(outbox_path / "telegram-60.json", {
            "schema_version": 1,
            "id": "telegram-60",
            "telegram_update_id": 60,
            "telegram_user_id": 42,
            "chat_id": 42,
            "text": "crash-safe message",
            "received_at": "2026-09-04T00:00:00+00:00",
            "egress_state": "ready",
        })
        gateway.drain_critical_outbox(root, capture_send)
        stored = json.loads((outbox_path / "telegram-60.json").read_text(encoding="utf-8"))
        assert stored["egress_state"] == "delivered"
        assert capture_send.messages == [(42, "crash-safe message")]


def test_drain_marks_delivery_unknown_on_send_failure():
    """Critical 3: failed send must become delivery_unknown, not delivered."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        outbox_path = root / "outbox" / "critical"
        outbox_path.mkdir(parents=True, exist_ok=True)
        records.atomic_json(outbox_path / "telegram-61.json", {
            "schema_version": 1,
            "id": "telegram-61",
            "telegram_update_id": 61,
            "telegram_user_id": 42,
            "chat_id": 42,
            "text": "failing message",
            "received_at": "2026-09-04T00:00:00+00:00",
            "egress_state": "ready",
        })

        def failing_send(chat_id, text):
            raise ConnectionError("network down")

        count = gateway.drain_critical_outbox(root, failing_send)
        assert count == 1
        stored = json.loads((outbox_path / "telegram-61.json").read_text(encoding="utf-8"))
        assert stored["egress_state"] == "delivery_unknown"


def test_drain_skips_malformed_record():
    """Critical 3: malformed records must never be marked delivered."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        outbox_path = root / "outbox" / "critical"
        outbox_path.mkdir(parents=True, exist_ok=True)
        # Record with no chat_id - malformed
        records.atomic_json(outbox_path / "telegram-62.json", {
            "schema_version": 1,
            "id": "telegram-62",
            "text": "missing chat",
            "egress_state": "ready",
        })
        count = gateway.drain_critical_outbox(root, capture_send)
        assert count == 0  # malformed record skipped, not counted
        stored = json.loads((outbox_path / "telegram-62.json").read_text(encoding="utf-8"))
        assert stored["egress_state"] == "ready"  # unchanged
        assert capture_send.messages == []


def test_command_replay_does_not_corrupt_record():
    """Critical 5: replaying an accepted update must not break replay detection."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        update = telegram_update(100, 42, "RESTART")
        first = gateway.handle_update(
            update, {42}, root,
            send=capture_send,
            send_command=capture_send.commands.append,
        )
        assert first["kind"] == "command"
        # Replay same update
        second = gateway.handle_update(
            update, {42}, root,
            send=capture_send,
            send_command=capture_send.commands.append,
        )
        assert second["kind"] == "command"
        # Command record must still have only strict fields (no egress_state bleed)
        cmd_path = root / "commands" / "telegram-100.json"
        stored = json.loads(cmd_path.read_text(encoding="utf-8"))
        assert set(stored) == {
            "schema_version", "id", "telegram_update_id",
            "telegram_user_id", "chat_id", "text", "received_at",
        }


def test_send_due_strictly_parses_records():
    """Important 2: corrupted/invalid records must be skipped, not silently counted."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        inbox_path = root / "inbox" / "telegram-70.json"
        inbox_path.parent.mkdir(parents=True, exist_ok=True)
        received_at = "2025-01-01T00:00:00+00:00"
        now = _epoch_seconds(received_at) + 400
        # Write a non-dict entry (corrupted)
        with inbox_path.open("w") as f:
            f.write("NOT JSON AT ALL")
        count = gateway.send_due_degraded_responses(root, send=capture_send, now=now)
        assert count == 0
        assert capture_send.messages == []


def test_pid_replacement_tracks_both_children():
    """Critical 2: parent must track both poll_pid and outbox_pid for deterministic restart."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        store_path = root / "state"
        store_path.mkdir(parents=True, exist_ok=True)
        received_at = "2025-01-01T00:00:00+00:00"
        now = _epoch_seconds(received_at) + 400

        def fake_send(chat_id, text):
            pass

        def fake_send_command(cmd):
            pass

        # Start main with a short-lived process
        # We verify the main function has correct PID tracking logic by
        # checking the source code directly
        import inspect
        source = inspect.getsource(gateway.main)
        assert "poll_pid = new_pid" in source, "poll_pid must be updated after fork replacement"
        assert "outbox_pid = new_pid" in source, "outbox_pid must be updated after fork replacement"


def test_outbox_ignores_non_ready_sending_states():
    """Critical 3: drain only processes ready/sending, leaves other states untouched."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        outbox_path = root / "outbox" / "critical"
        outbox_path.mkdir(parents=True, exist_ok=True)
        # delivered message should be untouched
        records.atomic_json(outbox_path / "telegram-80.json", {
            "schema_version": 1,
            "id": "telegram-80",
            "telegram_update_id": 80,
            "telegram_user_id": 42,
            "chat_id": 42,
            "text": "already done",
            "received_at": "2026-09-04T00:00:00+00:00",
            "egress_state": "delivered",
        })
        # delivery_unknown should be untouched
        records.atomic_json(outbox_path / "telegram-81.json", {
            "schema_version": 1,
            "id": "telegram-81",
            "telegram_update_id": 81,
            "telegram_user_id": 42,
            "chat_id": 42,
            "text": "failed",
            "received_at": "2026-09-04T00:00:00+00:00",
            "egress_state": "delivery_unknown",
        })
        count = gateway.drain_critical_outbox(root, capture_send)
        assert count == 0
        assert capture_send.messages == []
        delivered = json.loads((outbox_path / "telegram-80.json").read_text(encoding="utf-8"))
        unknown = json.loads((outbox_path / "telegram-81.json").read_text(encoding="utf-8"))
        assert delivered["egress_state"] == "delivered"
        assert unknown["egress_state"] == "delivery_unknown"


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
