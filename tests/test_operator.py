import unittest
from unittest.mock import patch

from cointos import api, opencode, prompts, schema, state, tasks
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

    def test_private_directories_come_from_a_machine_local_file_and_survive_every_ability(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            listing = Path(tmp) / "private-paths"
            listing.write_text("# comment\n\n/srv/secret/\n")
            with patch.object(opencode, "PRIVATE_PATHS", listing):
                for abilities in (["standard"], ["control", "network"]):
                    permission = opencode.settings(state.CONFIG, "key", {"abilities": abilities}, [])["permission"]
                    for kind in ("external_directory", "read", "edit"):
                        self.assertEqual(permission[kind]["/srv/secret/**"], "deny")
            with patch.object(opencode, "PRIVATE_PATHS", Path(tmp) / "absent"):
                self.assertEqual(opencode.private_paths(), [])

    def spawner(self, kind: str = "steward") -> dict:
        task = tasks.create(kind, tasks.SYSTEM, kind, "Scout.", [6], budget={"generation_tokens": 1000,
                                                                             "generation_seconds": 600})
        support.running(task, "spawner-1")
        state.L["agents"]["spawner-1"]["generation_tokens"] = 400
        return task

    def test_an_agent_run_starts_an_operator_paid_from_its_own_budget(self):
        task = self.spawner()
        operator = api.run_agent({"name": "land", "brief": "Land it.", "caller": support.caller(task, "spawner-1"),
                                  "budget": {"generation_tokens": 500, "generation_seconds": 100}})
        operator = state.L["tasks"][operator["task"]]
        self.assertEqual((operator["spawned_by"], operator["budget"]["generation_tokens"]), (task["id"], 500))
        self.assertEqual(schema.spent(state.L["agents"]["spawner-1"]),
                         {"generation_tokens": 900, "generation_seconds": 100})
        with self.assertRaisesRegex(ValueError, "only 100 tokens"):
            api.run_agent({"name": "more", "brief": "More.", "caller": support.caller(task, "spawner-1"),
                           "budget": {"generation_tokens": 101, "generation_seconds": 1}})
        with self.assertRaisesRegex(ValueError, "both budget limits"):
            api.run_agent({"name": "more", "brief": "More.", "caller": support.caller(task, "spawner-1")})
        with self.assertRaisesRegex(ValueError, "no ability its spawner lacks"):
            api.run_agent({"name": "more", "brief": "More.", "caller": support.caller(task, "spawner-1"),
                           "abilities": ["control"], "budget": {"generation_tokens": 1, "generation_seconds": 1}})

    def test_a_worker_cannot_start_an_operator_and_a_stranger_cannot_pose_as_a_run(self):
        task = self.spawner()
        with self.assertRaises(api.ApiError):
            api.run_agent({"name": "x", "brief": "X.", "caller": support.caller(task, "someone-else")})
        worker = dict(task, role="worker")
        with self.assertRaisesRegex(ValueError, "unreviewed"):
            tasks.request_operator("x", "X.", None, None, None, {"generation_tokens": 1, "generation_seconds": 1},
                                   (worker, state.L["agents"]["spawner-1"]))

    def test_invalid_ability_is_rejected_before_task_creation(self):
        with self.assertRaisesRegex(ValueError, "abilities"):
            tasks.request_operator("bad", "Brief", None, ["sudo"], None, None)
        self.assertFalse(state.L["tasks"])


if __name__ == "__main__":
    unittest.main()
