"""Agents' MCP tools: typed CLI commands without a shell, per-role catalogues, and messages
between tasks and the user."""
import json
import os
import unittest
from unittest.mock import patch

from cointos import api, cli, mcp, opencode, state
from tests import support


def direct(action, body, **_):
    return api.dispatch(action, body)


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

    def test_a_brief_with_quotes_and_newlines_queues_verbatim(self):
        brief = 'Fix the "parser" isn\'t `it`\n$(rm -rf /) && echo hi\nSummary: Fixes the parser quoting edge cases here.'
        output, failed = mcp.invoke("queue", {"project": "p", "name": "fix", "brief": brief, "stage": "implementation"}, "manager")
        self.assertFalse(failed, output)
        self.assertEqual(state.L["queue"]["p:fix"]["brief"].strip(), brief)

    def test_missing_arguments_are_refused_before_running(self):
        self.assertEqual(mcp.invoke("queue", {"project": "p", "name": "x"}, "manager"),
                         ("missing required argument(s): brief", True))
        self.assertTrue(mcp.invoke("finish", {}, "worker")[1])

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

    def test_agents_get_the_cointos_server_in_their_config(self):
        server = opencode.settings(state.CONFIG, "key", {"id": "p:x", "abilities": ["standard"]}, [], "worker-9")["mcp"]["cointos"]
        self.assertEqual(server["command"][-2:], ["-m", "cointos.mcp"])
        self.assertEqual((server["environment"]["COINTOS_TASK_ID"], server["environment"]["COINTOS_AGENT"]), ("p:x", "worker-9"))
        json.dumps(server)
