import copy
import unittest

from cointos import config


class LiveCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.installed = config.load()

    def test_daemon_policy_can_change_around_surviving_processes(self):
        candidate = copy.deepcopy(self.installed)
        candidate["reasoning"]["budgets"]["medium"] += 1
        candidate["recovery"]["generation_tokens"] += 1
        candidate["scheduler"]["slice_seconds"] += 1
        candidate["spawner"]["max_agents"] += 1

        self.assertEqual(config.live_incompatibilities(self.installed, candidate), [])

    def test_preserved_process_identity_must_not_change(self):
        changes = {
            "backend": lambda value: value + ".replacement",
            "lemonade": lambda value: value + "/replacement",
            "snapshots": lambda value: value + "-replacement",
            "server_cgroup": lambda value: value + "/replacement",
            "port": lambda value: value + 1,
            "work_model": lambda value: value + "-replacement",
            "models": lambda value: {**value, "replacement": copy.deepcopy(next(iter(value.values())))},
        }
        for key, change in changes.items():
            with self.subTest(key=key):
                candidate = copy.deepcopy(self.installed)
                candidate[key] = change(candidate[key])
                self.assertEqual(config.live_incompatibilities(self.installed, candidate), [key])

    def test_missing_installed_identity_is_incompatible(self):
        installed = copy.deepcopy(self.installed)
        del installed["port"]

        self.assertEqual(config.live_incompatibilities(installed, self.installed), ["port"])


if __name__ == "__main__":
    unittest.main()
