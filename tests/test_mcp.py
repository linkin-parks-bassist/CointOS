"""Agents' MCP tools: typed CLI commands without a shell, per-role catalogues, and messages
between tasks and the user."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from cointos import api, cli, client, mcp, opencode, state
from tests import support


def direct(action, body=None, **_):
    """The client's call made in-process: as this process's agent run when it is one."""
    return api.dispatch(action, {**(body or {}), **({"caller": client.caller()} if client.caller() else {})})


class Tools(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.project = support.project(self, support.repository(self))
        self.manager = support.running(support.queued(self.project, "plan", "Plan it", kind="command"), "manager-1")
        self.enterContext(patch.object(cli, "call", direct))
        self.enterContext(patch.object(mcp, "call", direct))
        self.enterContext(patch.object(mcp, "ledger", lambda: state.L))
        self.enterContext(patch.object(cli, "ledger", lambda: state.L))
        self.enterContext(patch.dict(os.environ, COINTOS_TASK_ID=self.manager["id"], COINTOS_AGENT="manager-1"))

    def names(self, role):
        return {tool["name"] for tool in mcp.catalogue(role)}

    def test_each_role_sees_its_own_tools(self):
        self.assertIn("queue", self.names("manager"))
        self.assertIn("land", self.names("integrator"))
        self.assertNotIn("queue", self.names("worker"))
        self.assertNotIn("land", self.names("worker"))
        self.assertTrue({"finish", "task", "send", "inbox"} <= self.names("worker"))
        self.assertEqual(mcp.invoke("land", {"summary": "x"}, "worker"), ("unknown tool 'land' for this role", True))
        self.assertIn("operator", self.names("manager"))
        self.assertIn("operator", self.names("steward"))
        self.assertNotIn("operator", self.names("worker"))

    def test_a_brief_with_quotes_and_newlines_queues_verbatim(self):
        brief = 'Fix the "parser" isn\'t `it`\n$(rm -rf /) && echo hi\nSummary: Fixes the parser quoting edge cases here.'
        output, failed = mcp.invoke("queue", {"project": "p", "name": "fix", "brief": brief, "stage": "implementation"}, "manager")
        self.assertFalse(failed, output)
        self.assertEqual(state.L["queue"]["p:fix"]["brief"].strip(), brief)

    def test_missing_arguments_are_refused_before_running(self):
        self.assertEqual(mcp.invoke("queue", {"project": "p", "name": "x"}, "manager"),
                         ("missing required argument(s): brief", True))
        self.assertTrue(mcp.invoke("finish", {}, "worker")[1])
        self.assertEqual(mcp.invoke("send", {"text": "hi"}, "worker"), ("missing required argument(s): to", True))

    def test_protocol_lists_and_calls_tools(self):
        listed = mcp.respond({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, "manager")
        self.assertIn("queue", {tool["name"] for tool in listed["result"]["tools"]})
        called = mcp.respond({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                              "params": {"name": "task", "arguments": {"task": self.manager["id"]}}}, "manager")
        self.assertFalse(called["result"]["isError"])
        self.assertIn(self.manager["id"], called["result"]["content"][0]["text"])
        self.assertIsNone(mcp.respond({"jsonrpc": "2.0", "method": "notifications/initialized"}, "manager"))

    def test_messages_reach_an_active_task_and_announce_themselves(self):
        worker = support.running(support.queued(self.project, "build"), "worker-1")
        self.assertEqual(mcp.invoke("send", {"to": worker["id"], "text": "Use the memo API"}, "manager"),
                         (f"sent to {worker['id']}", False))
        with patch.dict(os.environ, COINTOS_TASK_ID=worker["id"], COINTOS_AGENT="worker-1"):
            output, _ = mcp.invoke("task", {"task": worker["id"]}, "worker")
            self.assertIn("[1 unread message: call inbox]", output)
            self.assertEqual(mcp.invoke("inbox", {}, "worker"), (f"From {self.manager['id']}:\nUse the memo API", False))
            self.assertNotIn("unread", mcp.invoke("task", {"task": worker["id"]}, "worker")[0])

    def test_messages_need_a_live_sender_and_an_active_recipient(self):
        self.assertTrue(mcp.invoke("send", {"to": "p:nothing", "text": "hi"}, "manager")[1])
        with patch.dict(os.environ, COINTOS_AGENT="stale-run"):
            self.assertTrue(mcp.invoke("send", {"to": self.manager["id"], "text": "hi"}, "manager")[1])

    def test_the_user_can_message_an_agent_and_agents_can_reach_the_user(self):
        with patch.dict(os.environ, {"COINTOS_TASK_ID": "", "COINTOS_AGENT": ""}):
            self.assertEqual(api.dispatch("send", {"to": self.manager["id"], "text": "Prioritise tests"})["to"], self.manager["id"])
        self.assertIn("From user:\nPrioritise tests", mcp.invoke("inbox", {}, "manager")[0])
        with patch.object(api, "alert") as alert:
            mcp.invoke("send", {"to": "user", "text": "Need a decision"}, "manager")
        alert.assert_called_once_with(f"Message from {self.manager['id']}: Need a decision")

    def test_peers_show_other_runs_their_purpose_activity_and_changes(self):
        self.assertEqual(mcp.invoke("peers", {}, "manager")[0], "no other agents are running")
        worker = support.running(support.queued(self.project, "build", "Summary: Builds the parser front end.\nDo it"), "worker-1")
        worker["base_commit"] = support.git.head(worker["worktree"])
        (Path(worker["worktree"]) / "parser.c").write_text("int parse(void);\n")
        support.git.run(worker["worktree"], "add", "parser.c")
        state.L["agents"]["worker-1"]["doing"] = "edit: parser.c"
        output, failed = mcp.invoke("peers", {}, "manager")
        self.assertFalse(failed)
        self.assertIn(f"{worker['id']} (worker, running): Builds the parser front end.", output)
        self.assertIn("now: edit: parser.c", output)
        self.assertIn("parser.c", output.split("changed:")[1])
        self.assertNotIn(self.manager["id"] + " (", output)

    def test_external_mailbox_receives_without_phone_alerts_and_replies_as_itself(self):
        with patch.object(api, "alert") as alert:
            result, failed = mcp.invoke("send", {"to": "mailbox:codex", "text": "Hello Codex"}, "manager")
            self.assertFalse(failed, result)
            alert.assert_not_called()
        self.assertFalse(state.L["messages"][-1]["read"])
        with patch.dict(os.environ, COINTOS_TASK_ID="", COINTOS_AGENT=""):
            self.assertIn("Hello Codex", cli.COMMANDS["inbox"](cli.parser().parse_args(["inbox", "--mailbox", "codex"])))
            self.assertEqual(api.dispatch("inbox", {"mailbox": "codex"})["messages"], [])
            api.dispatch("send", {"mailbox": "codex", "to": self.manager["id"], "text": "Hello back"})
        self.assertIn("From mailbox:codex:\nHello back", mcp.invoke("inbox", {}, "manager")[0])

    def test_task_cannot_impersonate_or_read_external_mailbox(self):
        with self.assertRaises(api.ApiError):
            api.dispatch("inbox", {"caller": support.caller(self.manager, "manager-1"), "mailbox": "codex"})
        for target in ("mailbox:", "mailbox:bad/name", "mailbox:bad name"):
            self.assertTrue(mcp.invoke("send", {"to": target, "text": "hi"}, "manager")[1])

    def test_a_message_is_posted_once_into_the_recipients_live_session(self):
        from cointos import messages
        posted = []

        class Inline:  # the fixtures replace threading.Thread; deliver synchronously instead
            def __init__(self, target, args, daemon):
                self.run = lambda: target(*args)

            def start(self):
                self.run()

        self.enterContext(patch.object(messages.threading, "Thread", Inline))
        self.enterContext(patch.object(messages, "post", lambda *call: posted.append(call)))
        worker = support.running(support.queued(self.project, "build"), "worker-1")
        mcp.invoke("send", {"to": worker["id"], "text": "Use the memo API"}, "manager")
        messages.pending()  # no live session yet: the message waits
        self.assertEqual((posted, state.L["messages"][-1]["read"]), ([], False))
        state.L["agents"]["worker-1"].update(url="http://127.0.0.1:9", session="ses_1")
        messages.pending()
        messages.pending()
        self.assertEqual(posted, [("http://127.0.0.1:9", "ses_1", worker["worktree"],
                                   f'<message from="{self.manager["name"]} ({self.manager["id"]})">\nUse the memo API\n</message>')])
        self.assertTrue(state.L["messages"][-1]["read"])

    def test_a_failed_post_is_retried_later(self):
        from cointos import messages

        class Inline:
            def __init__(self, target, args, daemon):
                self.run = lambda: target(*args)

            def start(self):
                self.run()

        self.enterContext(patch.object(messages.threading, "Thread", Inline))
        attempts = []

        def flaky(*call):
            attempts.append(call)
            if len(attempts) == 1:
                raise OSError("connection refused")

        self.enterContext(patch.object(messages, "post", flaky))
        worker = support.running(support.queued(self.project, "build"), "worker-1")
        state.L["agents"]["worker-1"].update(url="http://127.0.0.1:9", session="ses_1")
        mcp.invoke("send", {"to": worker["id"], "text": "Hello"}, "manager")
        messages.pending()
        self.assertFalse(state.L["messages"][-1]["read"])
        messages.pending()
        self.assertEqual((len(attempts), state.L["messages"][-1]["read"]), (2, True))

    def test_every_task_gets_its_own_generated_name_for_life(self):
        from cointos import names, prompts
        worker = support.queued(self.project, "build")
        self.assertRegex(worker["name"], r"^[A-Z][a-z]{2,7}$")
        self.assertNotEqual(worker["name"], self.manager["name"])
        self.assertIn(f"Your name is {worker['name']}.", prompts.identity(worker))
        taken = {f"Name{i}" for i in range(50)} | {"Rako"}
        import random
        rng = random.Random(3)
        made = {names.invent(taken, rng) for _ in range(200)}
        self.assertEqual(len(made & {n.lower() for n in taken}), 0)
        self.assertGreater(len(made), 150, "names rarely collide")

    def test_agents_get_the_cointos_server_in_their_config(self):
        server = opencode.settings(state.CONFIG, "key", {"id": "p:x", "abilities": ["standard"]}, [], "worker-9")["mcp"]["cointos"]
        self.assertEqual(server["command"][-2:], ["-m", "cointos.mcp"])
        self.assertEqual((server["environment"]["COINTOS_TASK_ID"], server["environment"]["COINTOS_AGENT"]), ("p:x", "worker-9"))
        json.dumps(server)
