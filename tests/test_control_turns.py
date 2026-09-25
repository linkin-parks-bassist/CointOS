import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from ecosystem import cli, conversation, control_turns
from ecosystem.control_worker import _reap, process_turn
from ecosystem.telegram import accept_update, deliver_due_disaster_fallbacks
from tests.test_mvp_task_contracts import accepted_authority_policy, contract


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
    infer = lambda **_arguments: {"content": '{"response":"hiya.","deep_required":false}'}
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
def test_front_can_intentionally_finish_without_reply_or_deep_dispatch(_root):
    sent = []
    accept_update("token", update(82, "yippee"), {42},
                  send=lambda *_arguments: sent.append(True),
                  infer=lambda **_arguments: {
                      "content": '{"response":null,"deep_required":false}'})
    turn = control_turns.load("telegram-82")
    assert turn["front_state"] == "silent"
    assert turn["deep_state"] == "completed"
    assert turn["deep_skip_reason"] == "front_decided_no_deep_work"
    assert control_turns.reserve_next(os.getpid()) is None
    assert sent == []


@with_root
def test_deep_turn_can_finish_silently_after_front_reply(_root):
    accept_update("token", update(), {42}, send=lambda *_arguments: None,
                  infer=lambda **_arguments: {"content": '{"response":"already enough.","deep_required":true}'})
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
                  infer=lambda **_arguments: {"content": '{"response":"quick.","deep_required":true}'})
    assert control_turns.reserve_next(99999999) == "telegram-81"
    assert control_turns.recover_interrupted() == 1
    assert control_turns.load("telegram-81")["deep_state"] == "queued"


@with_root
def test_reaped_child_before_claim_releases_only_its_reservation(_root):
    accept_update("token", update(), {42}, send=lambda *_arguments: None,
                  infer=lambda **_arguments: {"content": '{"response":"quick.","deep_required":true}'})
    owner = os.getpid()
    assert control_turns.reserve_next(owner) == "telegram-81"
    active = {99101: "telegram-81"}
    with patch("ecosystem.control_worker.os.waitpid", return_value=(99101, 1)):
        _reap(active)
    assert active == {}
    assert control_turns.load("telegram-81")["deep_state"] == "queued"

    assert control_turns.reserve_next(owner) == "telegram-81"
    assert control_turns.claim_reserved("telegram-81", owner, owner)
    active = {99102: "telegram-81"}
    with patch("ecosystem.control_worker.os.waitpid", return_value=(99102, 1)):
        _reap(active)
    assert control_turns.load("telegram-81")["deep_state"] == "running"
    assert control_turns.reserve_next(owner) is None


@with_root
def test_delivered_generation_cancels_disaster_fallback(_root):
    sent = []
    accept_update("token", update(), {42}, send=lambda *_arguments: None,
                  infer=lambda **_arguments: {"content": '{"response":"quick.","deep_required":false}'})
    old = datetime.now(timezone.utc) + timedelta(minutes=6)
    with patch("ecosystem.control_turns.datetime") as clock:
        clock.now.return_value = old
        clock.fromisoformat.side_effect = datetime.fromisoformat
        assert deliver_due_disaster_fallbacks("token", send=lambda *_arguments: sent.append(True)) == 0
    assert sent == []


def _telegram_dispatches_accepted_contact_work(root: Path, identifier: int, role_marker: object,
                                                workspace: str | None = None,
                                                expected_default: str | None = None) -> None:
    accept_update("token", update(identifier, "inspect it"), {42},
                  send=lambda *_arguments: None,
                  infer=lambda **_arguments: {"content": '{"response":"I’ll inspect it.","deep_required":true}'})
    turn_id = f"telegram-{identifier}"
    owner = os.getpid()
    assert control_turns.reserve_next(owner) == turn_id
    assert control_turns.claim_reserved(turn_id, owner, owner)
    arguments = {"task": "inspect the invariant", "agent_name": "Noether"}
    if role_marker is not _OMITTED:
        arguments["role"] = role_marker
    if workspace is not None:
        arguments["workspace"] = workspace

    def controller(_message, _history, _initial, _live, execute):
        result = execute("queue_task", arguments)
        assert result["ok"] is True
        return {"followup": None}

    with patch("ecosystem.control_runtime.snapshot", return_value={"models": []}):
        process_turn(turn_id, send=lambda *_arguments: None, controller=controller)
    jobs = list((root / "state/jobs").glob("task-*.json"))
    assert len(jobs) == 1
    job = json.loads(jobs[0].read_text())
    assert job["task"] == "inspect the invariant"
    assert job["authority_profile"] == "contact_requested"
    expected_workspace = (str(Path(workspace).expanduser().resolve()) if workspace is not None
                          else expected_default or str(root.resolve()))
    assert job["scope"]["workspace"] == expected_workspace


_OMITTED = object()


@with_root
def test_telegram_dispatch_accepts_omitted_role_from_trusted_contact(root):
    _telegram_dispatches_accepted_contact_work(root, 82, _OMITTED, str(root / "contact_notes"))


@with_root
def test_telegram_dispatch_accepts_null_role_from_trusted_contact(root):
    source = root / "source-checkout"
    source.mkdir()
    (root / ".cointos-install.json").write_text(
        json.dumps({"source": {"root": str(source)}}), encoding="utf-8")
    _telegram_dispatches_accepted_contact_work(root, 83, None,
                                                expected_default=str(source.resolve()))


@with_root
def test_telegram_dispatch_accepts_unknown_role_from_trusted_contact(root):
    _telegram_dispatches_accepted_contact_work(root, 84, "mathematical_mongoose")


@with_root
def test_idempotent_task_key_does_not_duplicate_work(root):
    accepted_authority_policy(root)
    roles = root / "roles"
    roles.mkdir()
    (roles / "worker.md").write_text(
        "# Worker\n## Mission\nDo.\n## Permissions\nRead.\n## Approval required\nAsk.\n## Handoff\nReport.\n")
    inventory = {"models": [{"id": "model", "loaded": True}]}
    with patch("ecosystem.models.snapshot", return_value=inventory), patch("ecosystem.identity.generate", return_value="Journathan"):
        task_contract = contract(root, objective="do it")
        first = cli.enqueue_task("worker", "do it", model="model", idempotency_key="same",
                                 task_contract=task_contract)
    with patch("ecosystem.models.snapshot", side_effect=RuntimeError("model server unavailable")):
        second = cli.enqueue_task("worker", "do it", model="model", idempotency_key="same",
                                  task_contract=task_contract)
    assert first == second
    assert len(list((root / "state/jobs").glob("task-*.json"))) == 1
    assert json.loads((root / f"state/jobs/{first}.json").read_text())["agent_name"] == "Journathan"


@with_root
def test_replayed_amendment_does_not_modify_a_newer_task(root):
    accepted_authority_policy(root)
    roles = root / "roles"
    roles.mkdir()
    (roles / "worker.md").write_text(
        "# Worker\n## Mission\nDo.\n## Permissions\nRead.\n## Approval required\nAsk.\n## Handoff\nReport.\n")
    inventory = {"models": [{"id": "model", "loaded": True}]}
    with patch("ecosystem.models.snapshot", return_value=inventory), patch("ecosystem.identity.generate", return_value="Journathan"):
        original = cli.enqueue_task("worker", "agreement", source="telegram:42", model="model",
                                    task_contract=contract(root, objective="agreement"))
        assert cli.amend_latest_task("telegram:42", "worker", "argument", model="model",
                                     idempotency_key="turn:amend",
                                     task_contract=contract(root, objective="argument")) == original
        newer = cli.enqueue_task("worker", "new work", source="telegram:42", model="model",
                                 task_contract=contract(root, objective="new work"))
    assert cli.amend_latest_task("telegram:42", "worker", "argument", model="model",
                                 idempotency_key="turn:amend",
                                 task_contract=contract(root, objective="argument")) == original
    assert json.loads((root / f"state/jobs/{newer}.json").read_text())["task"] == "new work"


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
