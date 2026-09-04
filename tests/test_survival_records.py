import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from survival import records


def with_survival_root(function):
    def run():
        with tempfile.TemporaryDirectory() as temporary:
            function(Path(temporary))

    run.__name__ = function.__name__
    return run


def telegram_update(identifier: int, user_id: int, text: str, chat_id: int | None = None) -> dict:
    return {
        "update_id": identifier,
        "message": {
            "from": {"id": user_id},
            "chat": {"id": user_id if chat_id is None else chat_id},
            "text": text,
        },
    }


@with_survival_root
def test_atomic_json_replaces_a_complete_record(root):
    path = root / "state" / "record.json"
    records.atomic_json(path, {"state": "new"})
    records.atomic_json(path, {"state": "replaced"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"state": "replaced"}


@with_survival_root
def test_atomic_json_defaults_to_private_mode(root):
    path = root / "state" / "private.json"
    records.atomic_json(path, {"state": "private"})
    assert path.stat().st_mode & 0o777 == 0o600


@with_survival_root
def test_shared_atomic_json_has_final_mode_before_publication(root):
    path = root / "state" / "shared.json"
    observed = []
    replace = records.os.replace

    def observe_replace(source, destination):
        observed.append(Path(source).stat().st_mode & 0o777)
        replace(source, destination)

    with patch("survival.records.os.replace", side_effect=observe_replace):
        records.atomic_json(
            path, {"state": "shared"}, mode=records.SHARED_RECORD_MODE,
        )
    assert observed == [0o660]
    assert path.stat().st_mode & 0o777 == 0o660


@with_survival_root
def test_permission_failure_leaves_no_published_or_temporary_record(root):
    path = root / "state" / "shared.json"
    with patch("survival.records.os.fchmod", side_effect=OSError("mode failed")):
        with unittest.TestCase().assertRaisesRegex(OSError, "mode failed"):
            records.atomic_json(
                path, {"state": "shared"}, mode=records.SHARED_RECORD_MODE,
            )
    assert not path.exists()
    assert list(path.parent.iterdir()) == []


@with_survival_root
def test_record_modes_reject_implicit_or_overpermissive_values(root):
    path = root / "state" / "invalid.json"
    for mode in (True, 0o640, 0o666):
        with unittest.TestCase().assertRaisesRegex(ValueError, "mode"):
            records.atomic_json(path, {"state": "invalid"}, mode=mode)
    assert not path.parent.exists()


@with_survival_root
def test_append_event_preserves_each_jsonl_event(root):
    path = root / "events" / "commands.jsonl"
    records.append_event(path, {"event": "accepted", "id": "telegram-91"})
    records.append_event(path, {"event": "completed", "id": "telegram-91"})
    assert [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] == [
        {"event": "accepted", "id": "telegram-91"},
        {"event": "completed", "id": "telegram-91"},
    ]
    assert path.stat().st_mode & 0o777 == 0o600


@with_survival_root
def test_replayed_update_keeps_one_record(root):
    first = records.accept_update(root, telegram_update(91, 42, "RESTART"), {42})
    second = records.accept_update(root, telegram_update(91, 42, "RESTART"), {42})
    assert first["id"] == second["id"]
    assert len(list((root / "commands").glob("*.json"))) == 1
    assert (root / "commands" / "telegram-91.json").stat().st_mode & 0o777 == 0o600


@with_survival_root
def test_exclusive_command_mode_is_private_before_publication(root):
    path = root / "commands" / "telegram-92.json"
    observed = []
    link = records.os.link

    def observe_link(source, destination):
        observed.append(Path(source).stat().st_mode & 0o777)
        link(source, destination)

    with patch("survival.records.os.link", side_effect=observe_link):
        records.accept_update(root, telegram_update(92, 42, "RESTART"), {42})
    assert observed == [0o600]
    assert path.stat().st_mode & 0o777 == 0o600


@with_survival_root
def test_replayed_update_with_different_identity_fails_explicitly(root):
    records.accept_update(root, telegram_update(91, 42, "RESTART"), {42})
    with unittest.TestCase().assertRaisesRegex(ValueError, "identity"):
        records.accept_update(root, telegram_update(91, 42, "RESET"), {42})


@with_survival_root
def test_replay_rejects_boolean_in_persisted_update_identity(root):
    records.accept_update(root, telegram_update(1, 1, "RESTART"), {1})
    path = root / "commands" / "telegram-1.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["telegram_update_id"] = True
    records.atomic_json(path, stored)
    with unittest.TestCase().assertRaisesRegex(ValueError, "fields"):
        records.accept_update(root, telegram_update(1, 1, "RESTART"), {1})


@with_survival_root
def test_replay_rejects_persisted_record_with_extra_field(root):
    records.accept_update(root, telegram_update(91, 42, "RESTART"), {42})
    path = root / "commands" / "telegram-91.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["unit"] = "ssh.service"
    records.atomic_json(path, stored)
    with unittest.TestCase().assertRaisesRegex(ValueError, "fields"):
        records.accept_update(root, telegram_update(91, 42, "RESTART"), {42})


@with_survival_root
def test_replay_rejects_persisted_duplicate_json_field(root):
    records.accept_update(root, telegram_update(91, 42, "RESTART"), {42})
    path = root / "commands" / "telegram-91.json"
    path.write_text(
        '{"schema_version":1,"id":"telegram-91","telegram_update_id":91,'
        '"telegram_user_id":42,"chat_id":42,"text":"RESTART",'
        '"text":"RESTART","received_at":"2026-09-04T00:00:00+00:00"}',
        encoding="utf-8",
    )
    with unittest.TestCase().assertRaisesRegex(ValueError, "duplicate"):
        records.accept_update(root, telegram_update(91, 42, "RESTART"), {42})


@with_survival_root
def test_unauthorized_user_does_not_create_a_command(root):
    with unittest.TestCase().assertRaisesRegex(ValueError, "unauthorized"):
        records.accept_update(root, telegram_update(91, 7, "RESTART"), {42})
    assert not (root / "commands").exists()


@with_survival_root
def test_negative_update_id_is_rejected_before_persistence(root):
    with unittest.TestCase().assertRaisesRegex(ValueError, "invalid Telegram update"):
        records.accept_update(root, telegram_update(-1, 42, "RESTART"), {42})
    assert not (root / "commands").exists()


@with_survival_root
def test_update_write_failure_does_not_publish_a_partial_record(root):
    update = telegram_update(91, 42, "RESTART")
    with patch("survival.records.json.dump", side_effect=OSError("disk failed")):
        with unittest.TestCase().assertRaisesRegex(OSError, "disk failed"):
            records.accept_update(root, update, {42})
    assert not (root / "commands" / "telegram-91.json").exists()
    assert records.accept_update(root, update, {42})["id"] == "telegram-91"


@with_survival_root
def test_accepted_update_preserves_typed_ingress_identity(root):
    accepted = records.accept_update(root, telegram_update(91, 42, "how is scheduler?", chat_id=84), {42})
    assert accepted["id"] == "telegram-91"
    assert accepted["telegram_update_id"] == 91
    assert accepted["telegram_user_id"] == 42
    assert accepted["chat_id"] == 84
    assert accepted["text"] == "how is scheduler?"
    stored = json.loads((root / "commands" / "telegram-91.json").read_text(encoding="utf-8"))
    assert set(stored) == {
        "schema_version",
        "id",
        "telegram_update_id",
        "telegram_user_id",
        "chat_id",
        "text",
        "received_at",
    }


def load_tests(_loader, _tests, _pattern):
    functions = [value for name, value in globals().items()
                 if name.startswith("test_") and callable(value)]
    return unittest.TestSuite(unittest.FunctionTestCase(function) for function in functions)
