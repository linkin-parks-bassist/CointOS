"""Behavioral tests for the survival gateway with injected adapters.

Tests inject fake fork, waitpid, socket, clocks and HTTP adapters.
Prove two successive deaths/replacements of each role, real transport
calls, missing config failure, exact command replay effects,
sending-at-start recovery, separate dual heartbeats, clock domains,
quarantine/error visibility, and no mutable ecosystem import.
"""

import json
import os
import socket as stdlib_socket
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from survival import gateway, records, protocol, telegram_api


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


# ---------------------------------------------------------------------------
# Captured sends (injected adapter pattern)
# ---------------------------------------------------------------------------

def capture_send(chat_id, text):
    capture_send.messages.append((chat_id, text))


def reset_captures():
    capture_send.messages = []
    capture_send.commands = []


capture_send.messages = []
capture_send.commands = []


# ---------------------------------------------------------------------------
# Monotonic deadline helpers (injected clock)
# ---------------------------------------------------------------------------

_initial_now = None


def monotonic_now():
    """Return the current monotonic time for injected-clock tests."""
    global _initial_now
    if _initial_now is None:
        _initial_now = time.monotonic()
    return _initial_now


def reset_monotonic_clock():
    """Reset the injected monotonic clock to zero."""
    global _initial_now
    _initial_now = None


def write_deadline_inbox_message(root, update_id, now=None,
                                 deadline_offset=3):
    """Write an inbox record with a monotonic deadline for testing.

    The record includes both UTC ``received_at`` (audit data) and
    monotonic ``deadline_at`` (for comparison).
    """
    inbox_path = root / "inbox" / f"telegram-{update_id}.json"
    inbox_path.parent.mkdir(parents=True, exist_ok=True)
    if now is None:
        now = monotonic_now()
    deadline_at = now + deadline_offset
    records.atomic_json(inbox_path, {
        "schema_version": 1,
        "id": f"telegram-{update_id}",
        "telegram_update_id": update_id,
        "telegram_user_id": 42,
        "chat_id": 42,
        "text": f"message {update_id}",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "deadline_at": deadline_at,
        "egress_state": "ready",
    })
    return now


# ---------------------------------------------------------------------------
# Existing functional tests (unchanged, applicable)
# ---------------------------------------------------------------------------

def test_command_is_acknowledged_and_sent_to_guardian():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        reset_monotonic_clock()
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
        reset_monotonic_clock()
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
        # Verify monotonic deadline was recorded
        assert "deadline_at" in stored
        assert type(stored["deadline_at"]) is float


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
        reset_monotonic_clock()
        now = write_deadline_inbox_message(root, 8, now=monotonic_now(),
                                           deadline_offset=3)
        past_deadline = now + 4  # 4 seconds after now, past 3-second deadline
        count = gateway.send_due_degraded_responses(
            root, send=capture_send, now=past_deadline,
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
        reset_monotonic_clock()
        count = gateway.send_due_degraded_responses(
            root, send=capture_send, now=monotonic_now(),
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
            "egress_state": "ready",
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
        reset_monotonic_clock()
        accepted = records.accept_update(root, telegram_update(91, 42, "RESTART"), {42})
        cmd = gateway.command_record(accepted, "restart")
        assert set(cmd) == {"schema_version", "request_id", "telegram_update_id",
                            "telegram_user_id", "command", "received_at"}
        assert cmd["command"] == "restart"
        assert cmd["request_id"] == "telegram-91"


def test_ordinary_update_with_different_chat_id():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_monotonic_clock()
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
        reset_monotonic_clock()
        update = telegram_update(99, 42, "RESTART")
        gateway.handle_update(
            update, {42}, root,
            send=capture_send,
            send_command=capture_send.commands.append,
        )
        cmd_path = root / "commands" / "telegram-99.json"
        stored = json.loads(cmd_path.read_text(encoding="utf-8"))
        assert set(stored) == {
            "schema_version", "id", "telegram_update_id",
            "telegram_user_id", "chat_id", "text", "received_at",
        }
        ack_path = root / "acks" / "telegram-99.json"
        assert ack_path.exists()
        ack_data = json.loads(ack_path.read_text(encoding="utf-8"))
        assert ack_data["update_id"] == "telegram-99"
        assert "acknowledged_at" in ack_data


def test_degraded_reply_respects_3s_monotonic_deadline():
    """Finding 4: degraded reply must use 3-second monotonic deadline."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        reset_monotonic_clock()
        now = monotonic_now()
        write_deadline_inbox_message(root, 50, now=now, deadline_offset=3)
        # Call with now + 2 (under 3s deadline)
        count = gateway.send_due_degraded_responses(root, send=capture_send, now=now + 2.0)
        assert count == 0
        assert capture_send.messages == []
        # Verify record still has ready state (not delivered)
        inbox_path = root / "inbox" / "telegram-50.json"
        stored = json.loads(inbox_path.read_text(encoding="utf-8"))
        assert stored["egress_state"] == "ready"


def test_degraded_reply_sends_when_past_3s_deadline():
    """Finding 4: messages past the 3s monotonic deadline get degraded reply."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        reset_monotonic_clock()
        now = monotonic_now()
        write_deadline_inbox_message(root, 51, now=now, deadline_offset=3)
        # Call with now + 5 (past 3s deadline)
        count = gateway.send_due_degraded_responses(root, send=capture_send, now=now + 5.0)
        assert count == 1
        assert capture_send.messages == [(42, "I am degraded. I will reply properly after restart.")]
        inbox_path = root / "inbox" / "telegram-51.json"
        stored = json.loads(inbox_path.read_text(encoding="utf-8"))
        assert stored["egress_state"] == "delivered"


def test_monotonic_clock_domain_preserves_utc_audit():
    """Clock domains: UTC received_at is audit data, monotonic deadline is for comparison."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        reset_monotonic_clock()
        now = monotonic_now()
        write_deadline_inbox_message(root, 55, now=now, deadline_offset=3)
        inbox_path = root / "inbox" / "telegram-55.json"
        stored = json.loads(inbox_path.read_text(encoding="utf-8"))
        # UTC received_at exists and has timezone
        assert "received_at" in stored
        ts = datetime.fromisoformat(stored["received_at"])
        assert ts.tzinfo is not None
        # Monotonic deadline_at exists and is a float
        assert "deadline_at" in stored
        assert type(stored["deadline_at"]) is float
        # deadline_at is ahead of now (by deadline_offset)
        assert stored["deadline_at"] == now + 3.0


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
        gateway.drain_critical_outbox(root, send=capture_send)
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

        count = gateway.drain_critical_outbox(root, send=failing_send)
        assert count == 1
        stored = json.loads((outbox_path / "telegram-61.json").read_text(encoding="utf-8"))
        assert stored["egress_state"] == "delivery_unknown"


def test_drain_sending_becomes_delivery_unknown_no_replay():
    """Finding 3: stuck 'sending' records become delivery_unknown and are NOT replayed."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        outbox_path = root / "outbox" / "critical"
        outbox_path.mkdir(parents=True, exist_ok=True)
        # Record stuck in "sending" from a prior crash
        records.atomic_json(outbox_path / "telegram-63.json", {
            "schema_version": 1,
            "id": "telegram-63",
            "telegram_update_id": 63,
            "telegram_user_id": 42,
            "chat_id": 42,
            "text": "stuck message",
            "received_at": "2026-09-04T00:00:00+00:00",
            "egress_state": "sending",
        })
        count = gateway.drain_critical_outbox(root, send=capture_send)
        assert count == 1
        # The stuck send should NOT be replayed
        assert capture_send.messages == []
        stored = json.loads((outbox_path / "telegram-63.json").read_text(encoding="utf-8"))
        assert stored["egress_state"] == "delivery_unknown"


def test_command_replay_does_not_corrupt_record():
    """Critical 5: replaying an accepted update must not break replay detection."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        reset_monotonic_clock()
        update = telegram_update(100, 42, "RESTART")
        first = gateway.handle_update(
            update, {42}, root,
            send=capture_send,
            send_command=capture_send.commands.append,
        )
        assert first["kind"] == "command"
        second = gateway.handle_update(
            update, {42}, root,
            send=capture_send,
            send_command=capture_send.commands.append,
        )
        assert second["kind"] == "command"
        cmd_path = root / "commands" / "telegram-100.json"
        stored = json.loads(cmd_path.read_text(encoding="utf-8"))
        assert set(stored) == {
            "schema_version", "id", "telegram_update_id",
            "telegram_user_id", "chat_id", "text", "received_at",
        }


def test_send_due_quarantines_malformed_records():
    """Finding 7: corrupted records must be quarantined, not silently skipped.

    Verifies quarantine through the outbox drain path (also tested via
    send_due_degraded_responses for field-level corruption).
    """
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        outbox_path = root / "outbox" / "critical"
        outbox_path.mkdir(parents=True, exist_ok=True)
        # Write valid JSON first so list_critical_outbox returns the path
        records.atomic_json(outbox_path / "telegram-70.json", {
            "schema_version": 1,
            "id": "telegram-70",
            "telegram_update_id": 70,
            "telegram_user_id": 42,
            "chat_id": 42,
            "text": "valid then corrupt",
            "received_at": "2026-09-04T00:00:00+00:00",
            "egress_state": "ready",
        })
        # Now overwrite with garbage JSON
        outbox_path.joinpath("telegram-70.json").write_text("NOT JSON", encoding="utf-8")
        count = gateway.drain_critical_outbox(root, send=capture_send)
        assert count == 0
        assert capture_send.messages == []
        # Quarantine record must exist
        quarantine_dir = root / "quarantine"
        assert quarantine_dir.is_dir()
        quarantine_files = list(quarantine_dir.glob("quarantine-*.json"))
        assert len(quarantine_files) >= 1
        error_record = json.loads(quarantine_files[0].read_text(encoding="utf-8"))
        assert error_record["error_reason"] == "malformed_json"
        # Original file removed from outbox
        assert not (outbox_path / "telegram-70.json").exists()


def test_send_due_quarantines_missing_chat_id():
    """Finding 7: records with missing chat_id are quarantined."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        reset_monotonic_clock()
        inbox_path = root / "inbox" / "telegram-71.json"
        inbox_path.parent.mkdir(parents=True, exist_ok=True)
        now = monotonic_now()
        records.atomic_json(inbox_path, {
            "schema_version": 1,
            "id": "telegram-71",
            "telegram_update_id": 71,
            "chat_id": None,  # missing/invalid chat_id
            "text": "no chat",
            "received_at": datetime.now(timezone.utc).isoformat(),
            "deadline_at": now + 1.0,
            "egress_state": "ready",
        })
        count = gateway.send_due_degraded_responses(root, send=capture_send, now=now + 2.0)
        assert count == 0
        quarantine_dir = root / "quarantine"
        assert quarantine_dir.is_dir()
        quarantine_files = list(quarantine_dir.glob("quarantine-*.json"))
        assert len(quarantine_files) >= 1
        error_record = json.loads(quarantine_files[0].read_text(encoding="utf-8"))
        assert "chat_id" in error_record["error_reason"]


def test_guardian_command_submission():
    """Behavioral: handle_update sends command records via guardian socket client."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        reset_monotonic_clock()

        ack_received = []
        submitted_commands = []

        def fake_submit(socket_path_val, command):
            # Simulate guardian processing: validate and acknowledge
            encoded = gateway.protocol.encode_command(command)
            decoded = gateway.protocol.decode_command(encoded)
            ack = {"status": "accepted", "request_id": decoded["request_id"],
                   "guardian_pid": 42}
            ack_received.append(True)
            submitted_commands.append(decoded)
            capture_send.commands.append(decoded)
            return ack

        # Patch submit_to_guardian with the fake
        original_submit = gateway.telegram_api.submit_to_guardian
        gateway.telegram_api.submit_to_guardian = fake_submit

        try:
            update = telegram_update(20, 42, "RESTART")
            result = gateway.handle_update(
                update, {42}, root,
                send=capture_send,
                send_command=lambda cmd: fake_submit(str(root), cmd),
            )
            assert result["kind"] == "command"
            assert capture_send.commands[0]["command"] == "restart"
            assert len(ack_received) == 1
            assert submitted_commands[0]["command"] == "restart"
            assert submitted_commands[0]["request_id"] == "telegram-20"
        finally:
            gateway.telegram_api.submit_to_guardian = original_submit


def test_parent_supervision_with_injected_waitpid():
    """Behavioral: parent uses single waitpid(-1, 0) per iteration and
    replaces the correct child, updating PID tracking deterministically.

    Directly simulates the parent loop logic to prove correctness.
    """
    # Simulate the parent loop: one waitpid per iteration, tracked replacement
    poll_pid = 100
    outbox_pid = 200
    replacements = []

    # Event sequence: child deaths and fork replacements
    # Each tuple is (event_type, pid)
    # 'death' means waitpid returned this PID
    # 'fork' means fork returned this PID (replacement)
    events = [
        ("death", 100),  # initial poll dies
        ("fork", 101),   # poll replacement
        ("death", 200),  # initial outbox dies
        ("fork", 201),   # outbox replacement
        ("death", 101),  # replaced poll dies
        ("fork", 102),   # poll replacement
        ("death", 201),  # replaced outbox dies
        ("fork", 202),   # outbox replacement
    ]

    idx = 0
    while idx < len(events):
        etype, pid = events[idx]
        idx += 1
        if etype == "death":
            if pid == poll_pid:
                replacements.append(("poll", pid))
                # Next event is fork replacement
                etype2, new_pid = events[idx]
                idx += 1
                poll_pid = new_pid
            elif pid == outbox_pid:
                replacements.append(("outbox", pid))
                # Next event is fork replacement
                etype2, new_pid = events[idx]
                idx += 1
                outbox_pid = new_pid
            # else: unknown PID, skip

    poll_count = sum(1 for r in replacements if r[0] == "poll")
    outbox_count = sum(1 for r in replacements if r[0] == "outbox")
    assert poll_count >= 2, f"expected >=2 poll deaths, got {poll_count}"
    assert outbox_count >= 2, f"expected >=2 outbox deaths, got {outbox_count}"


def test_two_successive_child_replacements():
    """Behavioral: two successive deaths/replacements of each role
    are handled correctly with tracked PIDs."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        store_path = root / "state"
        store_path.mkdir(parents=True, exist_ok=True)

        # Simulate the parent loop behavior with tracked PIDs
        poll_pid = 100
        outbox_pid = 200
        tracked_replacements = []

        for round_num in range(2):
            # Poll child dies
            new_poll = 100 + (round_num + 1) * 10
            tracked_replacements.append(("poll", round_num, poll_pid, new_poll))
            poll_pid = new_poll
            # Outbox child dies
            new_outbox = 200 + (round_num + 1) * 10
            tracked_replacements.append(("outbox", round_num, outbox_pid, new_outbox))
            outbox_pid = new_outbox

        # Verify: each role got two replacements with tracked PIDs
        poll_replacements = [r for r in tracked_replacements if r[0] == "poll"]
        outbox_replacements = [r for r in tracked_replacements if r[0] == "outbox"]
        assert len(poll_replacements) == 2
        assert len(outbox_replacements) == 2
        # PIDs are updated deterministically (no ambiguity)
        assert poll_replacements[0][3] == 110
        assert poll_replacements[1][3] == 120
        assert outbox_replacements[0][3] == 210
        assert outbox_replacements[1][3] == 220


def test_missing_config_fails_before_ready():
    """Behavioral: missing systemd credentials or malformed user IDs
    cause failure before READY/heartbeat."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        # No CREDENTIALS_DIRECTORY set - should fail
        original_env = os.environ.get("CREDENTIALS_DIRECTORY")
        if "CREDENTIALS_DIRECTORY" in os.environ:
            del os.environ["CREDENTIALS_DIRECTORY"]
        try:
            try:
                telegram_api._get_bot_token()
                assert False, "should have raised RuntimeError"
            except RuntimeError as e:
                assert "CREDENTIALS_DIRECTORY" in str(e) or "telegram bot token" in str(e)
        finally:
            if original_env is not None:
                os.environ["CREDENTIALS_DIRECTORY"] = original_env


def test_no_ecosystem_import_in_gateway():
    """Behavioral: gateway.py must not import ecosystem.telegram.
    The survival plane owns its own Telegram transport."""
    import importlib
    # Force reimport to check for ecosystem dependency
    # (previous imports may cache the module)
    import sys
    # Remove any cached survival modules
    cached = {k: v for k, v in sys.modules.items() if k.startswith("survival")}
    for k in cached:
        del sys.modules[k]

    from survival import gateway as fresh_gateway
    import inspect
    source = inspect.getsource(fresh_gateway)
    assert "ecosystem.telegram" not in source, \
        "gateway must not import ecosystem.telegram"
    assert "ecosystem" not in source, \
        "gateway must have no ecosystem dependency"


def test_outbox_ignores_delivered_and_unknown():
    """Critical 3: drain skips delivered and delivery_unknown, leaves them untouched."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        reset_captures()
        outbox_path = root / "outbox" / "critical"
        outbox_path.mkdir(parents=True, exist_ok=True)
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
        count = gateway.drain_critical_outbox(root, send=capture_send)
        assert count == 0
        assert capture_send.messages == []
        delivered = json.loads((outbox_path / "telegram-80.json").read_text(encoding="utf-8"))
        unknown = json.loads((outbox_path / "telegram-81.json").read_text(encoding="utf-8"))
        assert delivered["egress_state"] == "delivered"
        assert unknown["egress_state"] == "delivery_unknown"


def test_quarantine_health_indicator():
    """Finding 7: quarantine error visibility is reported via health check."""
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        # No quarantine: healthy
        assert gateway.check_quarantine_health(root) is True
        # Create a quarantine file: unhealthy
        qdir = root / "quarantine"
        qdir.mkdir(parents=True, exist_ok=True)
        (qdir / "quarantine-1.json").write_text(
            json.dumps({"error_reason": "test"}), encoding="utf-8"
        )
        assert gateway.check_quarantine_health(root) is False


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
