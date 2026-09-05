import hashlib
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ecosystem import cli
from ecosystem.evidence import DEFAULT_MAXIMUM_BYTES, read_evidence, record_contribution
from ecosystem.executor import discovery_evidence


def _contract(workspace, read_paths, write_paths, evidence_items=5):
    return {
        "objective": "Inspect one bounded note",
        "scope": {
            "workspace": str(workspace),
            "read_paths": [str(path) for path in read_paths],
            "write_paths": [str(path) for path in write_paths],
        },
        "authority_profile": "bounded_maintenance",
        "requirements": {"required_capabilities": ["tool-calling"],
                         "minimum_context_tokens": 16384},
        "acceptance": [{"kind": "artifact"}],
        "budget": {"run_seconds": 300, "task_seconds": 900, "maximum_attempts": 2,
                   "maximum_output_bytes": 65536,
                   "maximum_evidence_items": evidence_items, "maximum_children": 0},
        "source_key": "test:evidence", "parent_job_id": None,
        "stop_condition": "Stop after one bounded note.",
    }


def test_evidence_reader_rejects_escape():
    with TemporaryDirectory() as tmp:
        scope = {"workspace": tmp, "read_paths": [str(Path(tmp) / "agent_notes")],
                 "write_paths": []}
        try:
            read_evidence(scope, "../outside", 0, {"maximum_bytes": 2048, "maximum_items": 1})
        except ValueError:
            pass
        else:
            raise AssertionError("scope escape accepted")


def test_evidence_reader_rejects_absolute_path():
    with TemporaryDirectory() as tmp:
        scope = {"workspace": tmp, "read_paths": [str(Path(tmp) / "notes")],
                 "write_paths": []}
        try:
            read_evidence(scope, "/etc/passwd", 0,
                          {"maximum_bytes": 2048, "maximum_items": 1})
        except ValueError:
            pass
        else:
            raise AssertionError("absolute path accepted")


def test_symlink_escape_is_rejected():
    with TemporaryDirectory() as tmp:
        notes = Path(tmp) / "notes"
        notes.mkdir()
        outside = Path(tmp) / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        (notes / "link.txt").symlink_to(outside)
        scope = {"workspace": tmp, "read_paths": [str(notes)], "write_paths": []}
        try:
            read_evidence(scope, "notes/link.txt", 0,
                          {"maximum_bytes": 2048, "maximum_items": 1})
        except ValueError:
            pass
        else:
            raise AssertionError("symlink escape accepted")


def test_bounded_read_pages_across_calls():
    with TemporaryDirectory() as tmp:
        notes = Path(tmp) / "notes"
        notes.mkdir()
        source = notes / "page.txt"
        content = "line one\nline two\nline three\n"
        source.write_text(content, encoding="utf-8")
        scope = {"workspace": tmp, "read_paths": [str(notes)], "write_paths": []}
        pool = len(content.encode("utf-8"))
        cursor = 0
        collected = ""
        pages = 0
        while pool > 0:
            result = read_evidence(scope, "notes/page.txt", cursor,
                                   {"maximum_bytes": min(pool, 12),
                                    "maximum_items": 3})
            assert set(result) == {"path", "digest", "observed_at", "text",
                                   "next_cursor", "truncated", "items_read"}
            assert result["path"] == str(source.resolve())
            collected += result["text"]
            pool -= len(result["text"].encode("utf-8"))
            cursor = result["next_cursor"]
            pages += 1
            if not result["truncated"]:
                break
            assert pages < 5, "paging did not converge"
        assert collected == content
        assert pages == 3


def test_utf8_boundary_does_not_split_character():
    with TemporaryDirectory() as tmp:
        notes = Path(tmp) / "notes"
        notes.mkdir()
        source = notes / "wide.txt"
        content = "aaaaa\u20acbbbbb\n"
        source.write_text(content, encoding="utf-8")
        scope = {"workspace": tmp, "read_paths": [str(notes)], "write_paths": []}
        first = read_evidence(scope, "notes/wide.txt", 0,
                              {"maximum_bytes": 7, "maximum_items": 3})
        assert first["text"] == "aaaaa"
        assert first["next_cursor"] == 5
        assert first["truncated"] is True
        second = read_evidence(scope, "notes/wide.txt", first["next_cursor"],
                               {"maximum_bytes": 64, "maximum_items": 3})
        assert second["text"] == "\u20acbbbbb\n"
        assert second["truncated"] is False
        assert first["text"] + second["text"] == content


def test_event_tail_paging_counts_whole_events():
    with TemporaryDirectory() as tmp:
        notes = Path(tmp) / "notes"
        notes.mkdir()
        source = notes / "events.jsonl"
        events = [json.dumps({"seq": index, "note": "x" * 20}) + "\n"
                  for index in range(5)]
        source.write_text("".join(events), encoding="utf-8")
        scope = {"workspace": tmp, "read_paths": [str(notes)], "write_paths": []}
        line_len = len(events[0].encode("utf-8"))
        first = read_evidence(scope, "notes/events.jsonl", 0,
                              {"maximum_bytes": line_len + 19, "maximum_items": 10})
        assert first["items_read"] == 1
        assert first["truncated"] is True
        second = read_evidence(scope, "notes/events.jsonl", first["next_cursor"],
                               {"maximum_bytes": 2048, "maximum_items": 2})
        assert second["items_read"] == 2
        third = read_evidence(scope, "notes/events.jsonl", second["next_cursor"],
                              {"maximum_bytes": 2048, "maximum_items": 10})
        assert third["items_read"] == 2
        assert third["truncated"] is False
        assert first["items_read"] + second["items_read"] + third["items_read"] == 5
        assembled = (first["text"] + second["text"] + third["text"]).splitlines()
        assert [json.loads(line)["seq"] for line in assembled] == [0, 1, 2, 3, 4]


def test_event_page_stops_at_item_budget():
    with TemporaryDirectory() as tmp:
        notes = Path(tmp) / "notes"
        notes.mkdir()
        source = notes / "events.jsonl"
        source.write_text("".join(json.dumps({"n": i}) + "\n" for i in range(4)),
                          encoding="utf-8")
        scope = {"workspace": tmp, "read_paths": [str(notes)], "write_paths": []}
        result = read_evidence(scope, "notes/events.jsonl", 0,
                               {"maximum_bytes": 2048, "maximum_items": 2})
        assert result["items_read"] == 2
        assert result["truncated"] is True
        rest = read_evidence(scope, "notes/events.jsonl", result["next_cursor"],
                             {"maximum_bytes": 2048, "maximum_items": 10})
        assert rest["items_read"] == 2
        assert rest["truncated"] is False


def test_changed_source_invalidates_digest():
    with TemporaryDirectory() as tmp:
        notes = Path(tmp) / "notes"
        notes.mkdir()
        source = notes / "drift.txt"
        source.write_text("first revision\n", encoding="utf-8")
        scope = {"workspace": tmp, "read_paths": [str(notes)], "write_paths": []}
        first = read_evidence(scope, "notes/drift.txt", 0,
                              {"maximum_bytes": 2048, "maximum_items": 1})
        source.write_text("second revision\n", encoding="utf-8")
        second = read_evidence(scope, "notes/drift.txt", 0,
                               {"maximum_bytes": 2048, "maximum_items": 1})
        assert first["digest"] != second["digest"]
        assert second["digest"] == hashlib.sha256(
            b"second revision\n").hexdigest()


def test_empty_file_yields_empty_page():
    with TemporaryDirectory() as tmp:
        notes = Path(tmp) / "notes"
        notes.mkdir()
        source = notes / "empty.txt"
        source.write_text("", encoding="utf-8")
        scope = {"workspace": tmp, "read_paths": [str(notes)], "write_paths": []}
        result = read_evidence(scope, "notes/empty.txt", 0,
                               {"maximum_bytes": 2048, "maximum_items": 1})
        assert result["text"] == ""
        assert result["items_read"] == 0
        assert result["truncated"] is False
        assert result["next_cursor"] == 0
        past = read_evidence(scope, "notes/empty.txt", 99,
                             {"maximum_bytes": 2048, "maximum_items": 1})
        assert past["text"] == "" and past["truncated"] is False


def test_exhausted_budget_stays_honest_about_remaining_data():
    with TemporaryDirectory() as tmp:
        notes = Path(tmp) / "notes"
        notes.mkdir()
        (notes / "data.txt").write_text("data\n", encoding="utf-8")
        scope = {"workspace": tmp, "read_paths": [str(notes)], "write_paths": []}
        result = read_evidence(scope, "notes/data.txt", 0,
                               {"maximum_bytes": 0, "maximum_items": 0})
        assert result["text"] == ""
        assert result["items_read"] == 0
        assert result["truncated"] is True


def test_invalid_utf8_is_explicit_failure():
    with TemporaryDirectory() as tmp:
        notes = Path(tmp) / "notes"
        notes.mkdir()
        (notes / "binary.txt").write_bytes(b"\xff\xfe broken")
        scope = {"workspace": tmp, "read_paths": [str(notes)], "write_paths": []}
        try:
            read_evidence(scope, "notes/binary.txt", 0,
                          {"maximum_bytes": 2048, "maximum_items": 1})
        except ValueError:
            pass
        else:
            raise AssertionError("invalid UTF-8 accepted")


def test_record_contribution_appends_identity():
    with TemporaryDirectory() as tmp, patch.object(cli, "ROOT", Path(tmp)):
        root = Path(tmp)
        contract = _contract(root, [root / "notes"], [root / "notes"])
        job = {"id": "task-evidence-1", "agent_name": "Sol",
               "task_contract": contract}
        (root / "state" / "jobs").mkdir(parents=True)
        cli.atomic_json(root / "state" / "jobs" / "task-evidence-1.json", job)
        first = record_contribution(root, job, "notes/candidate.md",
                                    "first observation")
        second = record_contribution(root, job, "notes/candidate.md",
                                     "second observation")
        text = (root / "notes" / "candidate.md").read_text(encoding="utf-8")
        assert "job=task-evidence-1 agent=Sol" in text
        assert "first observation" in text and "second observation" in text
        assert text.index("first observation") < text.index("second observation")
        assert first["path"] == str((root / "notes" / "candidate.md").resolve())
        assert second["digest"] == hashlib.sha256(
            (root / "notes" / "candidate.md").read_bytes()).hexdigest()
        assert (root / "logs" / "runs").exists()


def test_record_contribution_rejects_uncontracted_path():
    with TemporaryDirectory() as tmp, patch.object(cli, "ROOT", Path(tmp)):
        root = Path(tmp)
        contract = _contract(root, [root / "notes"], [root / "notes"])
        job = {"id": "task-evidence-2", "agent_name": "Sol",
               "task_contract": contract}
        (root / "state" / "jobs").mkdir(parents=True)
        cli.atomic_json(root / "state" / "jobs" / "task-evidence-2.json", job)
        try:
            record_contribution(root, job, "elsewhere/notes.md", "text")
        except ValueError:
            pass
        else:
            raise AssertionError("uncontracted write accepted")


def test_record_contribution_requires_durable_job():
    with TemporaryDirectory() as tmp, patch.object(cli, "ROOT", Path(tmp)):
        root = Path(tmp)
        (root / "state" / "jobs").mkdir(parents=True)
        job = {"id": "task-ghost", "agent_name": "Sol",
               "task_contract": _contract(root, [root / "notes"],
                                          [root / "notes"])}
        try:
            record_contribution(root, job, "notes/candidate.md", "text")
        except ValueError:
            pass
        else:
            raise AssertionError("contribution without durable record accepted")


def test_discovery_evidence_adapter_derives_scope_and_limits():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        contract = _contract(root, [root / "notes"], [root / "notes"],
                             evidence_items=5)
        job = {"task_contract": contract,
               "remaining_budget": dict(contract["budget"])}
        authority = discovery_evidence(job)
        assert authority["scope"] == {
            "workspace": str(root),
            "read_paths": [str(root / "notes")],
            "write_paths": [str(root / "notes")],
        }
        assert authority["limits"] == {
            "maximum_bytes": DEFAULT_MAXIMUM_BYTES, "maximum_items": 5}
        try:
            discovery_evidence({"task_contract": None})
        except ValueError:
            pass
        else:
            raise AssertionError("contractless discovery accepted")


def load_tests(loader, tests, ignore):
    return unittest.TestSuite([
        unittest.FunctionTestCase(test_evidence_reader_rejects_escape),
        unittest.FunctionTestCase(test_evidence_reader_rejects_absolute_path),
        unittest.FunctionTestCase(test_symlink_escape_is_rejected),
        unittest.FunctionTestCase(test_bounded_read_pages_across_calls),
        unittest.FunctionTestCase(test_utf8_boundary_does_not_split_character),
        unittest.FunctionTestCase(test_event_tail_paging_counts_whole_events),
        unittest.FunctionTestCase(test_event_page_stops_at_item_budget),
        unittest.FunctionTestCase(test_changed_source_invalidates_digest),
        unittest.FunctionTestCase(test_empty_file_yields_empty_page),
        unittest.FunctionTestCase(test_exhausted_budget_stays_honest_about_remaining_data),
        unittest.FunctionTestCase(test_invalid_utf8_is_explicit_failure),
        unittest.FunctionTestCase(test_record_contribution_appends_identity),
        unittest.FunctionTestCase(test_record_contribution_rejects_uncontracted_path),
        unittest.FunctionTestCase(test_record_contribution_requires_durable_job),
        unittest.FunctionTestCase(test_discovery_evidence_adapter_derives_scope_and_limits),
    ])
