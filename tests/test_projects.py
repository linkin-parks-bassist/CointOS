import json
import subprocess
import tempfile
import unittest
from pathlib import Path

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
