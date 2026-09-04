import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from ecosystem import cli, conversation, control_turns
from ecosystem.control_worker import process_turn
from ecosystem.telegram import accept_update, deliver_due_disaster_fallbacks


def update(identifier=81, text="hello"):
    return {"update_id": identifier, "message": {
        "from": {"id": 42}, "chat": {"id": 42}, "text": text,
    }}


def with_root(function):
    def run():
        with tempfile.TemporaryDirectory() as temporary, patch.object(cli, "ROOT", Path(temporary)):
            cli.initialize()
            function(Path(temporary))
    run.__name__ = function.__name__
    return run


@with_root
def test_duplicate_update_has_one_user_record_and_one_front_delivery(_root):
    sent = []
    infer = lambda **_arguments: {"content": "hiya."}
    sender = lambda token, chat_id, message: sent.append((token, chat_id, message))
    accept_update("token", update(), {42}, send=sender, infer=infer)
    accept_update("token", update(), {42}, send=sender, infer=infer)
    assert sent == [("token", 42, "hiya.")]
    assert [entry["content"] for entry in conversation.recent(42)] == ["hello", "hiya."]


@with_root
def test_front_failure_preserves_deep_turn_without_canned_reply(_root):
    sent = []
    def fail(**_arguments):
        raise TimeoutError("front timed out")
    accept_update("token", update(), {42}, send=lambda *_arguments: sent.append(True), infer=fail)
    turn = control_turns.load("telegram-81")
    assert turn["front_state"] == "failed"
    assert turn["deep_state"] == "queued"
    assert sent == []


@with_root
def test_deep_turn_can_finish_silently_after_front_reply(_root):
    accept_update("token", update(), {42}, send=lambda *_arguments: None,
                  infer=lambda **_arguments: {"content": "already enough."})
    assert control_turns.reserve_next(111) == "telegram-81"
    assert control_turns.claim_reserved("telegram-81", 111, 222)
    process_turn("telegram-81", send=lambda *_arguments: (_ for _ in ()).throw(AssertionError("sent")),
                 controller=lambda *_arguments: {"followup": None})
    turn = control_turns.load("telegram-81")
    assert turn["deep_state"] == "completed"
    assert "followup_delivered_at" not in turn


@with_root
def test_interrupted_reserved_turn_is_recovered(_root):
    accept_update("token", update(), {42}, send=lambda *_arguments: None,
                  infer=lambda **_arguments: {"content": "quick."})
    assert control_turns.reserve_next(99999999) == "telegram-81"
    assert control_turns.recover_interrupted() == 1
    assert control_turns.load("telegram-81")["deep_state"] == "queued"


@with_root
def test_delivered_generation_cancels_disaster_fallback(_root):
    sent = []
    accept_update("token", update(), {42}, send=lambda *_arguments: None,
                  infer=lambda **_arguments: {"content": "quick."})
    old = datetime.now(timezone.utc) + timedelta(minutes=6)
    with patch("ecosystem.control_turns.datetime") as clock:
        clock.now.return_value = old
        clock.fromisoformat.side_effect = datetime.fromisoformat
        assert deliver_due_disaster_fallbacks("token", send=lambda *_arguments: sent.append(True)) == 0
    assert sent == []


def _telegram_enqueues_role(root: Path, identifier: int, role_marker: object) -> None:
    accept_update("token", update(identifier, "inspect it"), {42},
                  send=lambda *_arguments: None,
                  infer=lambda **_arguments: {"content": "I’ll inspect it."})
    turn_id = f"telegram-{identifier}"
    owner = os.getpid()
    assert control_turns.reserve_next(owner) == turn_id
    assert control_turns.claim_reserved(turn_id, owner, owner)
    arguments = {"task": "inspect the invariant", "agent_name": "Noether"}
    if role_marker is not _OMITTED:
        arguments["role"] = role_marker

    def controller(_message, _history, _initial, _live, execute):
        assert execute("queue_task", arguments)["ok"] is True
        return {"followup": None}

    with patch("ecosystem.control_runtime.snapshot", return_value={"models": []}):
        process_turn(turn_id, send=lambda *_arguments: None, controller=controller)
    jobs = list((root / "state/jobs").glob("task-*.json"))
    assert len(jobs) == 1
    expected = None if role_marker is _OMITTED else role_marker
    assert json.loads(jobs[0].read_text(encoding="utf-8"))["role"] == expected


_OMITTED = object()


@with_root
def test_telegram_dispatch_accepts_omitted_role(root):
    _telegram_enqueues_role(root, 82, _OMITTED)


@with_root
def test_telegram_dispatch_accepts_null_role(root):
    _telegram_enqueues_role(root, 83, None)


@with_root
def test_telegram_dispatch_preserves_unknown_role(root):
    _telegram_enqueues_role(root, 84, "mathematical_mongoose")


@with_root
def test_idempotent_task_key_does_not_duplicate_work(root):
    roles = root / "roles"
    roles.mkdir()
    (roles / "worker.md").write_text(
        "# Worker\n## Mission\nDo.\n## Permissions\nRead.\n## Approval required\nAsk.\n## Handoff\nReport.\n")
    inventory = {"models": [{"id": "model", "loaded": True}]}
    with patch("ecosystem.models.snapshot", return_value=inventory), patch("ecosystem.identity.generate", return_value="Journathan"):
        first = cli.enqueue_task("worker", "do it", model="model", idempotency_key="same")
    with patch("ecosystem.models.snapshot", side_effect=RuntimeError("model server unavailable")):
        second = cli.enqueue_task("worker", "do it", model="model", idempotency_key="same")
    assert first == second
    assert len(list((root / "state/jobs").glob("task-*.json"))) == 1
    assert json.loads((root / f"state/jobs/{first}.json").read_text())["agent_name"] == "Journathan"


@with_root
def test_replayed_amendment_does_not_modify_a_newer_task(root):
    roles = root / "roles"
    roles.mkdir()
    (roles / "worker.md").write_text(
        "# Worker\n## Mission\nDo.\n## Permissions\nRead.\n## Approval required\nAsk.\n## Handoff\nReport.\n")
    inventory = {"models": [{"id": "model", "loaded": True}]}
    with patch("ecosystem.models.snapshot", return_value=inventory), patch("ecosystem.identity.generate", return_value="Journathan"):
        original = cli.enqueue_task("worker", "agreement", source="telegram:42", model="model")
        assert cli.amend_latest_task("telegram:42", "worker", "argument", model="model",
                                     idempotency_key="turn:amend") == original
        newer = cli.enqueue_task("worker", "new work", source="telegram:42", model="model")
    assert cli.amend_latest_task("telegram:42", "worker", "argument", model="model",
                                 idempotency_key="turn:amend") == original
    assert json.loads((root / f"state/jobs/{newer}.json").read_text())["task"] == "new work"


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
