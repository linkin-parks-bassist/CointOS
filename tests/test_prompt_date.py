"""A clock rollover must not rewrite an established agent system prefix."""
import json
import unittest
from unittest.mock import patch

from cointos import gateway, prompts, state, tasks
from tests import support


class PromptDate(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        self.enterContext(patch.object(gateway.journal, "write"))
        self.tid = tasks.create("steward", tasks.SYSTEM, "scout", "Look", [6])["id"]
        state.L["tasks"][self.tid]["prompt_date"] = "Sun Sep 27 2026"
        state.L["agents"]["agent"] = {"task": self.tid}

    def messages(self, date):
        return [{"role": "system", "content": "Tools and instructions\n<env>\n"
                 "  Working directory: /tmp/p\n  Today's date: " + date + "\n</env>"},
                {"role": "user", "content": "Implement A"}]

    def test_midnight_and_restart_preserve_the_prefix(self):
        before = self.messages("Sun Sep 27 2026")
        after = self.messages("Mon Sep 28 2026")
        expected = gateway.stable_environment(before, "agent")
        persisted = json.loads(json.dumps(state.L))
        state.L.clear()
        state.L.update(state.fresh(persisted))
        state.L["agents"]["agent"] = {"task": self.tid}  # daemon adoption
        self.assertEqual(gateway.stable_environment(after, "agent"), expected)
        self.assertIn("Task start date: Sun Sep 27 2026", expected[0]["content"])
        self.assertIn("run date for the current date and time", expected[0]["content"])
        self.assertIn("Today's date: Sun Sep 27 2026", before[0]["content"])

    def test_other_clients_are_unchanged(self):
        messages = self.messages("Mon Sep 28 2026")
        self.assertIs(gateway.stable_environment(messages, "user"), messages)
        self.assertIs(gateway.stable_environment(messages, "coin"), messages)

    def test_only_the_environment_date_changes(self):
        messages = self.messages("Mon Sep 28 2026")
        messages[0]["content"] += "\nToday's date: Mon Sep 28 2026"
        messages[1]["content"] = "<env>\nToday's date: Mon Sep 28 2026\n</env>"
        result = gateway.stable_environment(messages, "agent")
        self.assertEqual(result[1], messages[1])
        self.assertTrue(result[0]["content"].endswith("Today's date: Mon Sep 28 2026"))
        self.assertIn("Working directory: /tmp/p", result[0]["content"])

    def test_task_date_comes_from_its_creation_timestamp(self):
        with patch.object(tasks, "now", return_value=1790500000), patch.object(
                tasks.time, "strftime", return_value="fixed date") as formatted:
            task = tasks.create("steward", tasks.SYSTEM, "scout", "B", [6])
        self.assertEqual(task["prompt_date"], "fixed date")
        self.assertEqual(formatted.call_args.args[1], tasks.time.localtime(1790500000))

    def test_complete_system_context_is_pinned_by_digest_across_runs(self):
        first = self.messages("Sun Sep 27 2026")
        first.insert(1, {"role": "system", "content": "Knowledge-tree startup:\nfirst tree"})
        expected = gateway.stable_environment(first, "agent")
        task = state.L["tasks"][self.tid]
        digest = task["system_context"]
        pinned = json.loads(state.L["system_contexts"][digest])
        self.assertEqual(pinned, expected[:-1])

        changed = self.messages("Mon Sep 28 2026")
        changed.insert(1, {"role": "system", "content": "Knowledge-tree startup:\nchanged tree"})
        self.assertEqual(gateway.stable_environment(changed, "agent"), expected)

        persisted = json.loads(json.dumps(state.L))
        state.L.clear()
        state.L.update(state.fresh(persisted))
        state.L["agents"]["agent"] = {"task": self.tid}
        self.assertEqual(gateway.stable_environment(changed, "agent"), expected)

    def test_prompt_digest_is_journalled_without_prompt_text(self):
        gateway.stable_environment(self.messages("Sun Sep 27 2026"), "agent")
        record = gateway.journal.write.call_args.args[0]
        self.assertEqual(record["event"], "system prompt")
        self.assertEqual(len(record["digest"]), 64)
        self.assertEqual(len(record["components"]), 1)
        self.assertNotIn("prompt", record)

    def test_fresh_managed_request_exposes_exact_rendered_role_prefix(self):
        task = state.L["tasks"][self.tid]
        body = {"messages": self.messages("Sun Sep 27 2026")}
        body["messages"][-1]["content"] = prompts.launch_text(task, tasks.SYSTEM)

        def render(config, model, conversation):
            text = "|".join(str(message.get("content", "")) for message in conversation["messages"])
            return {"tokens": list(text.encode()) + [999], "reader": {}}

        with patch.object(gateway.BACKEND, "render", side_effect=render) as renderer:
            rendered = gateway.render_request(body, "agent", state.CONFIG["work_model"], {})
        prefix = prompts.shared_launch_prefix(task)
        expected = len((body["messages"][0]["content"].replace(
            "Today's date: Sun Sep 27 2026",
            "Task start date: Sun Sep 27 2026 (fixed; run date for the current date and time)") + "|" + prefix).encode())
        self.assertEqual(rendered["shared"], expected)
        self.assertEqual(renderer.call_count, 2)

    def test_continuation_is_rendered_only_once(self):
        state.L["tasks"][self.tid]["session"] = "session"
        body = {"messages": self.messages("Sun Sep 27 2026")}
        body["messages"][-1]["content"] = "Continue."
        with patch.object(gateway.BACKEND, "render", return_value={"tokens": [1, 2], "reader": {}}) as renderer:
            rendered = gateway.render_request(body, "agent", state.CONFIG["work_model"], {})
        self.assertNotIn("shared", rendered)
        renderer.assert_called_once()
