import unittest
from unittest.mock import patch

from cointos import opencode, prompts, state, tasks
from tests import support


class OperatorTasks(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)

    def test_system_operator_has_explicit_scope_abilities_effort_and_budget(self):
        task = tasks.request_operator("inspect", "Inspect the runtime.", None, ["standard", "network"],
                                      "low", {"generation_tokens": 1234})
        self.assertEqual(task["id"], "system:operator-inspect-1")
        self.assertIsNone(task["branch"])
        self.assertEqual(task["abilities"], ["standard", "network"])
        self.assertEqual(task["reasoning_effort"], "low")
        self.assertEqual(task["budget"]["generation_tokens"], 1234)
        self.assertIn("Ad-hoc operator assignment", prompts.launch_text(task, tasks.place(task)))
        with self.assertRaisesRegex(ValueError, "already active"):
            tasks.request_operator("inspect", "Again.", None, None, None, None)

    def test_project_operator_uses_project_priority_and_an_isolated_branch(self):
        project = {"name": "p", "path": "/tmp/p", "main_branch": "main", "priority": 7, "enabled": True}
        with patch.dict(state.CONFIG, projects=[project]):
            task = tasks.request_operator("fix", "Make the bounded change.", "p", ["standard"], None, None)
        self.assertEqual(task["rank"], [1, 7])
        self.assertEqual(task["branch"], "work/operator-fix-1")
        self.assertIn("/tmp/.worktrees/p/operator-fix-1", task["worktree"])

    def test_capabilities_change_actual_opencode_permissions(self):
        standard = opencode.settings(state.CONFIG, "key", {"abilities": ["standard"]}, [])["permission"]
        powerful = opencode.settings(state.CONFIG, "key", {"abilities": ["control", "network"]}, [])["permission"]
        self.assertEqual((standard["websearch"], powerful["websearch"]), ("deny", "allow"))
        self.assertIn("cointos stop*", standard["bash"])
        self.assertNotIn("cointos stop*", powerful["bash"])

    def test_invalid_ability_is_rejected_before_task_creation(self):
        with self.assertRaisesRegex(ValueError, "abilities"):
            tasks.request_operator("bad", "Brief", None, ["sudo"], None, None)
        self.assertFalse(state.L["tasks"])


if __name__ == "__main__":
    unittest.main()
