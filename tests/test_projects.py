import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cointos import config, projects


class ProjectRegistry(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.registry = self.root / "projects.json"
        self.config = {"projects": []}

    def tearDown(self):
        self.temporary.cleanup()

    def repo(self, name):
        path = self.root / name
        path.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True)
        return path

    def test_add_update_remove_are_atomic_and_priority_ordered(self):
        later = projects.add(self.config, {"name": "later", "path": str(self.repo("later")),
                                                   "main_branch": "main", "priority": 20}, self.registry)
        first = projects.add(self.config, {"name": "first", "path": str(self.repo("first")),
                                                   "main_branch": "main", "priority": 10}, self.registry)
        self.assertEqual(["first", "later"], [p["name"] for p in self.config["projects"]])
        self.assertTrue(later["enabled"])
        projects.update(self.config, "later", {"priority": 5, "enabled": False}, self.registry)
        stored = json.loads(self.registry.read_text())
        self.assertEqual(1, stored["version"])
        self.assertEqual(["later", "first"], [p["name"] for p in stored["projects"]])
        self.assertFalse(stored["projects"][0]["enabled"])
        projects.remove(self.config, "later", self.registry)
        self.assertEqual([first["name"]], [p["name"] for p in self.config["projects"]])

    def test_duplicate_name_and_repository_are_rejected(self):
        path = self.repo("one")
        projects.add(self.config, {"name": "one", "path": str(path)}, self.registry)
        with self.assertRaisesRegex(ValueError, "already registered"):
            projects.add(self.config, {"name": "ONE", "path": str(self.repo("other"))}, self.registry)
        with self.assertRaisesRegex(ValueError, "already registered"):
            projects.add(self.config, {"name": "alias", "path": str(path)}, self.registry)

    def test_new_project_commits_all_orientation_routes_before_enrollment(self):
        real_run = subprocess.run

        def initialize(args, **options):
            if args[:3] != ["kt", "init", "--project"]:
                return real_run(args, **options)
            target = Path(options["cwd"])
            real_run(["git", "config", "user.name", "Test"], cwd=target, check=True)
            real_run(["git", "config", "user.email", "test@example.invalid"], cwd=target, check=True)
            for path, body in {"where/am/i.md": args[3], "what/is/the/spec.md": "", "what/is/the/plan.md": ""}.items():
                leaf = target / ".knowledge" / path
                leaf.parent.mkdir(parents=True, exist_ok=True)
                leaf.write_text(body)
            return subprocess.CompletedProcess(args, 0, "", "")

        def write_answer(target, question, body):
            leaf = Path(target) / ".knowledge" / (question.replace(" ", "/") + ".md")
            leaf.parent.mkdir(parents=True, exist_ok=True)
            leaf.write_text(body)

        for failing in (False, True):
            with self.subTest(failed_tree_write=failing):
                target = self.root / ("failed" if failing else "created")
                candidate = {"name": target.name, "path": str(target), "enabled": False}
                policy = {"manifest": "checks/contracts.json", "protected": ["checks/**"], "non_code": ["*.md"]}
                self.config = {"projects": [], "project_defaults": {"test_policy": policy}}
                if self.registry.exists():
                    self.registry.unlink()
                effect = RuntimeError("tree write failed") if failing else write_answer
                with patch.object(projects.subprocess, "run", side_effect=initialize), \
                        patch.object(projects.kt, "write", side_effect=effect):
                    if failing:
                        with self.assertRaisesRegex(RuntimeError, "tree write failed"):
                            projects.create(self.config, candidate, self.registry)
                        self.assertFalse(self.registry.exists())
                        self.assertEqual(self.config["projects"], [])
                        continue
                    created = projects.create(self.config, candidate, self.registry)
                self.assertFalse(created["enabled"])
                self.assertEqual(created["test_policy"], policy)
                self.assertIsNot(created["test_policy"], policy)
                for path in ("where/am/i.md", "what/is/the/spec.md", "what/is/the/plan.md", "what/is/broken.md"):
                    committed = real_run(["git", "show", "HEAD:.knowledge/" + path], cwd=target,
                                         check=True, capture_output=True, text=True)
                    if path == "what/is/broken.md":
                        self.assertEqual(committed.stdout, "No known defects have been established.")
                self.assertEqual(json.loads(self.registry.read_text())["projects"], [created])

    def test_partial_test_policy_has_the_complete_landing_shape(self):
        policy = {"manifest": "checks.json"}
        created = projects.add(self.config, {"name": "partial", "path": str(self.repo("partial")),
                                             "test_policy": policy}, self.registry)
        self.assertEqual(created["test_policy"], {"manifest": "checks.json", "protected": [], "non_code": []})
        self.assertEqual(policy, {"manifest": "checks.json"})

    def test_failed_persistence_leaves_both_registry_projections_unchanged(self):
        projects.add(self.config, {"name": "one", "path": str(self.repo("one"))}, self.registry)
        initial = copy.deepcopy(self.config)
        saved = self.registry.read_bytes()
        other = self.repo("other")
        operations = {
            "add": lambda: projects.add(self.config, {"name": "other", "path": str(other)}, self.registry),
            "update": lambda: projects.update(self.config, "one", {"priority": 1, "enabled": False}, self.registry),
            "remove": lambda: projects.remove(self.config, "one", self.registry),
        }
        for name, operation in operations.items():
            with self.subTest(operation=name):
                self.config = copy.deepcopy(initial)
                shared = self.config["projects"]
                with patch.object(projects, "write_json", side_effect=OSError("disk full")):
                    with self.assertRaisesRegex(OSError, "disk full"):
                        operation()
                self.assertEqual(self.config, initial)
                self.assertIs(self.config["projects"], shared)
                self.assertEqual(self.registry.read_bytes(), saved)

    def test_operational_config_reads_the_separate_registry(self):
        repo = self.repo("registered")
        operational = self.root / "cointos.json"
        operational.write_text(json.dumps({"trees": [], "projects": [{"name": "legacy", "path": "/nope"}]}))
        self.registry.write_text(json.dumps({"version": 1, "projects": [
            {"name": "registered", "path": str(repo), "main_branch": "main", "priority": 7, "enabled": True}
        ]}))
        loaded = config.load(operational, self.registry)
        self.assertEqual(["registered"], [p["name"] for p in loaded["projects"]])
        self.assertEqual(str(repo), loaded["projects"][0]["path"])


if __name__ == "__main__":
    unittest.main()
