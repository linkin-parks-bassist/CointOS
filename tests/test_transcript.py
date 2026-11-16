"""A failed agent's whole record, readable by whoever works out what went wrong."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from cointos import cli, transcript


class Transcript(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.database = self.root / "opencode.db"
        connection = sqlite3.connect(self.database)
        connection.execute("pragma journal_mode=wal")
        connection.executescript("create table message(id, session_id, data); create table part(id, message_id, session_id, data);")
        connection.execute("insert into message values('m1', 's1', ?)", (json.dumps({"role": "user"}),))
        connection.execute("insert into message values('m2', 's1', ?)", (json.dumps({"role": "assistant"}),))
        for identifier, message, part in (
                ("p1", "m1", {"type": "text", "text": "Do the job."}),
                ("p3", "m2", {"type": "text", "text": "Done, apparently."}),
                ("p2", "m2", {"type": "reasoning", "text": "This is getting out of hand."}),
                ("p4", "m2", {"type": "tool", "tool": "bash", "state": {"status": "completed", "input": {"command": "make"}, "output": "error: nope"}}),
                ("p5", "m2", {"type": "step-start"})):
            connection.execute("insert into part values(?, ?, 's1', ?)", (identifier, message, json.dumps(part)))
        connection.commit()
        self.addCleanup(connection.close)

    def test_it_keeps_reasoning_and_tool_output_in_order(self):
        text, messages = transcript.render(self.database, ["s1"])
        self.assertEqual(messages, 2)
        self.assertLess(text.index("Do the job."), text.index("out of hand"))
        self.assertLess(text.index("out of hand"), text.index("Done, apparently."))
        self.assertIn('"command": "make"', text)
        self.assertIn("error: nope", text)
        self.assertNotIn("step-start", text)

    def test_the_log_is_an_index_with_entries_by_number(self):
        found = transcript.entries(self.database, ["s1"])
        self.assertEqual([e["kind"] for e in found], ["user", "thought", "reply", "tool"])
        self.assertEqual({e["turn"] for e in found[1:]}, {1})
        index = transcript.view(found)
        self.assertIn("#2 t1 thought", index)
        self.assertIn("getting out of hand", transcript.view(found, show="2"))
        self.assertNotIn("Do the job", transcript.view(found, show="2-3"))
        only = transcript.view(found, kind="reply")
        self.assertIn("#3", only)
        self.assertNotIn("#2 ", only)
        self.assertIn("#1", transcript.view(found, grep="the job"))

    def test_coins_own_turns_read_the_same_way(self):
        journal = self.root / "turns.jsonl"
        journal.write_text("\n".join(json.dumps(row) for row in (
            {"kind": "user", "content": "what was my squat"},
            {"kind": "assistant", "reasoning": "check the log", "content": ""},
            {"kind": "tool", "name": "fs_read", "input": {"path": "x"}, "output": "50x3"},
            {"kind": "assistant", "content": "50x3"})) + "\nnot json\n")
        found = transcript.coin_entries(journal)
        self.assertEqual([e["kind"] for e in found], ["user", "thought", "tool", "reply"])
        self.assertIn("fs_read", found[2]["text"])

    def test_a_missing_session_says_so(self):
        self.assertIn("no messages on record", transcript.render(self.database, ["gone"])[0])

    def test_managed_readers_present_native_denials_without_changing_stored_history(self):
        raw = 'The user has specified a rule which prevents you from using this specific tool call. PRIVATE RULES'
        part = {'type': 'tool', 'tool': 'bash', 'state': {
            'status': 'error', 'input': {'command': 'git status'}, 'error': raw}}
        with sqlite3.connect(self.database) as connection:
            connection.execute("insert into part values('p6', 'm2', 's1', ?)", (json.dumps(part),))
        paths = {'s1': self.database}
        public_entries = transcript.entries(paths, ['s1'], public=True)
        self.assertIn("outside this run's permitted scope", public_entries[-1]['text'])
        self.assertIn('git status', public_entries[-1]['text'])
        self.assertNotIn('PRIVATE RULES', transcript.render(paths, ['s1'], public=True)[0])
        self.assertIn(raw, transcript.entries(paths, ['s1'])[-1]['text'])
        self.assertIn(raw, transcript.render(paths, ['s1'])[0])
        with patch.object(transcript, 'task_sources', return_value=(['s1'], paths, [])):
            for export in (False, True):
                shown = transcript.read_task({}, self.root, export=export, public=True, show='1-9')['text']
                self.assertIn("outside this run's permitted scope", shown)
                self.assertNotIn('PRIVATE RULES', shown)
        self.assertEqual([(e['kind'], e['turn']) for e in public_entries],
                         [(e['kind'], e['turn']) for e in transcript.entries(paths, ['s1'])])

    def test_permission_presentation_preserves_program_output_and_other_errors(self):
        raw = 'The user has specified a rule which prevents you from using this specific tool call. program diagnostic'
        for tool, role, state in [
                ('bash', 'assistant', {'status': 'completed', 'output': raw, 'exit': 1}),
                ('bash', 'assistant', {'status': 'error', 'error': 'ordinary failure'}),
                ('custom_server', 'assistant', {'status': 'error', 'error': raw}),
                ('bash', 'user', {'status': 'error', 'error': raw}),
                ('bash', 'assistant', {'status': 'error', 'output': raw, 'error': raw})]:
            part = {'type': 'tool', 'tool': tool, 'state': state}
            with self.subTest(tool=tool, role=role, state=state):
                self.assertEqual(transcript._part(part, public=True, role=role), transcript._part(part))

    def test_it_finds_every_run_of_the_task_only(self):
        agents = self.root / "agents"
        for agent, task, session in (("a", "p:job", "s1"), ("b", "p:other", "s9"), ("c", "p:job", "s2")):
            (agents / agent).mkdir(parents=True)
            (agents / agent / "run.json").write_text(json.dumps({"task": task, "session": session}))
        (agents / "bad").mkdir()
        (agents / "bad/run.json").write_text("{")
        found = transcript.sessions_of({"id": "p:job", "session": "s3", "previous_sessions": ["s0"]}, agents)
        self.assertEqual(set(found), {"s0", "s1", "s2", "s3"})
        self.assertEqual((found[0], found[-1]), ("s0", "s3"))

    def test_the_command_writes_a_file_and_says_where(self):
        out = self.root / "out.txt"
        with patch.object(cli, "ledger", return_value={"tasks": {"p:job": {"id": "p:job", "session": "s1"}}}), \
                patch.object(transcript, "database", return_value=self.database):
            message = cli.write_transcript("p:job", str(out))
        self.assertIn(str(out), message)
        self.assertIn("2 messages", message)
        self.assertIn("out of hand", out.read_text())
        with patch.object(cli, "ledger", return_value={"tasks": {}}), self.assertRaises(SystemExit):
            cli.write_transcript("p:none", None)
