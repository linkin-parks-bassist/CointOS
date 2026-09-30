"""Task records and their pinned metadata: stage, reasoning effort, run budget."""
import json
import unittest
from unittest.mock import patch

from cointos import api, gateway, opencode, queues, runs, schema, state, tasks
from tests import support


class Metadata(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        self.project = support.project(self, support.repository(self))

    def test_queue_metadata_is_pinned_on_the_task_and_survives_persistence(self):
        queues.add(self.project, "queued", "tests", "Adversarial tests", "test-contract", "medium")
        self.assertEqual(queues.add(self.project, "queued", "tests", "Adversarial tests", "test-contract", "medium"), "tests")
        with self.assertRaisesRegex(ValueError, "already exists"):
            queues.add(self.project, "queued", "tests", "Adversarial tests", "test-contract", "low")
        task = tasks.create("item", self.project, "tests", "Adversarial tests", [4], item="tests")
        restored = json.loads(json.dumps(state.L))["tasks"][task["id"]]
        self.assertEqual((restored["stage"], restored["reasoning_effort"], restored["record"]),
                         ("test-contract", "medium", "p:tests"))

    def test_stage_default_explicit_override_and_invalid_values(self):
        self.assertEqual(state.CONFIG["reasoning"]["budgets"], {"low": 256, "medium": 384, "xhigh": 1024})
        config = {"reasoning": {"default": "low", "test-contract": "medium"}}
        self.assertEqual(schema.default_effort(config, {"kind": "integrate", "stage": None}), "low")
        self.assertEqual(schema.default_effort(config, {"kind": "item", "stage": "implementation"}), "low")
        self.assertEqual(schema.default_effort(config, {"kind": "item", "stage": "test-contract"}), "medium")
        managed = {"reasoning": {"default": "low", "manager": "medium"}}
        self.assertEqual(schema.default_effort(managed, {"kind": "decompose", "stage": None}), "medium")
        self.assertEqual(schema.default_effort(managed, {"kind": "breakdown", "stage": None}), "medium")
        self.assertEqual(schema.default_effort(managed, {"kind": "item", "stage": "implementation"}), "low")
        self.assertEqual(schema.default_effort(config, {"kind": "item", "stage": "test-contract",
                                                         "reasoning_effort": "xhigh"}), "xhigh")
        with self.assertRaises(ValueError):
            queues.add(self.project, "queued", "x", "Do it", reasoning_effort="high")
        with self.assertRaises(ValueError):
            queues.add(self.project, "queued", "x", "Do it", stage="whatever")

    def test_gateway_task_metadata_wins_but_a_user_request_can_choose(self):
        task = tasks.create("steward", tasks.SYSTEM, "scout", "Look", [6], reasoning_effort="low")
        state.L["agents"]["a"] = {"task": task["id"]}
        body = {"reasoning_effort": "medium", "chat_template_kwargs": {"preserve_thinking": True}}
        self.assertEqual(gateway.template_options(body, "a"), {"reasoning_effort": "low", "preserve_thinking": True})
        self.assertEqual(gateway.template_options(body, "user")["reasoning_effort"], "medium")

    def test_a_reasoning_change_applies_from_the_next_reply(self):
        queues.add(self.project, "queued", "t", "Do it", reasoning_effort="xhigh")
        task = tasks.create("item", self.project, "t", "Do it", [4], item="t")
        state.L["agents"]["a"] = {"task": task["id"], "reasoning_effort": "xhigh"}
        state.L["thoughts"]["old"] = {"agent": "a", "reasoning_effort": "xhigh"}
        rendered = gateway.template_options({}, "a")
        tasks.set_reasoning(task["id"], "low")
        self.assertEqual((rendered["reasoning_effort"], state.L["thoughts"]["old"]["reasoning_effort"]), ("xhigh", "xhigh"))
        self.assertEqual(gateway.template_options({}, "a")["reasoning_effort"], "low")
        self.assertEqual((state.L["queue"]["p:t"]["reasoning_effort"], state.L["agents"]["a"]["reasoning_effort"]), ("low", "low"))
        with self.assertRaises(ValueError):
            tasks.set_reasoning(task["id"], "high")
        with self.assertRaises(ValueError):
            tasks.set_reasoning("absent", "low")

    def test_implementers_cannot_edit_protected_tests(self):
        project = {**self.project, "test_policy": {"manifest": "tests/contracts.json", "protected": ["tests/**"]}}
        queues.add(project, "queued", "impl", "Implement it")
        task = tasks.create("item", project, "impl", "Implement it", [4], item="impl")
        edit = opencode.settings(state.CONFIG, "key", task, runs.protected(task, project))["permission"]["edit"]
        self.assertEqual((edit[f"{task['worktree']}/tests/**"], edit["tests/contracts.json"], edit["*"]), ("deny", "deny", "allow"))
        self.assertEqual(runs.protected({**task, "stage": "test-contract"}, project), [])


class Budgets(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        support.quiet(self)
        self.project = support.project(self, support.repository(self))

    def test_invalid_budgets_are_refused_before_any_record_exists(self):
        for value in [[], {"unknown": 1}, {"generation_tokens": True}, {"generation_tokens": 1.5},
                      {"generation_seconds": float("nan")}, {"generation_seconds": float("inf")},
                      {"generation_tokens": 0}, {"generation_seconds": -1}]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                queues.add(self.project, "queued", "child", "Brief", budget=value)
            self.assertNotIn("p:child", state.L["queue"])

    def test_a_queued_budget_is_pinned_at_creation_and_survives_restart(self):
        override = {"generation_tokens": 1234}
        queues.add(self.project, "queued", "child", "Brief", budget=override)
        with self.assertRaisesRegex(ValueError, "already exists"):
            queues.add(self.project, "queued", "child", "Brief", budget={"generation_tokens": 1235})
        task = tasks.create("item", self.project, "child", "Brief", [4], item="child")
        self.assertEqual(task["budget"], {"generation_tokens": 1234, "generation_seconds": 1800})
        restored = state.fresh(json.loads(json.dumps(state.L)))
        with patch.dict(state.CONFIG["recovery"], generation_seconds=9999):
            self.assertEqual(restored["tasks"][task["id"]]["budget"]["generation_seconds"], 1800)

    def test_only_waiting_work_changes_budget_and_the_other_limit_stays(self):
        api.dispatch("queue", {"project": "p", "name": "child", "brief": "Brief", "budget": {"generation_seconds": 90}})
        self.assertEqual(api.dispatch("budget", {"task": "p:child", "budget": {"generation_tokens": 2000}})["budget"],
                         {"generation_tokens": 2000, "generation_seconds": 90})
        task = tasks.create("item", self.project, "child", "Brief", [4], item="child")
        tasks.set_budget(task["id"], {"generation_tokens": 555})
        self.assertEqual(task["budget"], {"generation_tokens": 555, "generation_seconds": 90})
        task["status"] = "running"
        with self.assertRaisesRegex(ValueError, "inactive waiting"):
            tasks.set_budget(task["id"], {"generation_tokens": 777})
        self.assertEqual(task["budget"]["generation_tokens"], 555)


class Identity(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)

    def test_scheduler_tasks_are_numbered_and_queue_tasks_are_their_records(self):
        first = tasks.create("steward", tasks.SYSTEM, "loose-ends", "", [6])
        second = tasks.create("steward", tasks.SYSTEM, "loose-ends", "", [6])
        self.assertEqual((first["id"], second["id"]), ("system:loose-ends-1", "system:loose-ends-2"))
        self.assertEqual(first["title"], "loose-ends")
        project = support.project(self, support.repository(self))
        worker = support.queued(project, "parser")
        self.assertEqual((worker["id"], worker["record"], worker["branch"]), ("p:parser", "p:parser", "work/parser"))


if __name__ == "__main__":
    unittest.main()
