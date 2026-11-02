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

    def test_a_missing_session_says_so(self):
        self.assertIn("no messages on record", transcript.render(self.database, ["gone"])[0])

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
