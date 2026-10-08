"""The ledger migration: an old stored-status ledger becomes the current schema, its packets and
idle worker branches lose the retired work report, and a second run changes nothing."""
import copy
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import unittest

from cointos import git, queues, state
from tests import support

loader = importlib.machinery.SourceFileLoader("upgrade_ledger", str(Path(__file__).parents[1] / "scripts/upgrade-ledger"))
spec = importlib.util.spec_from_loader("upgrade_ledger", loader)
upgrade_ledger = importlib.util.module_from_spec(spec)
loader.exec_module(upgrade_ledger)


def task(task_id, kind, status, record_hash, **fields):
    project, _, item = task_id.partition(":")
    return {"id": task_id, "kind": kind, "status": status, "record_hash": record_hash, "place": project,
            "item": item.removeprefix("decompose-"), "branch": None, "worktree": None, "receipt": None,
            "note": None, "brief": "b", "updated_at": 5, **fields}


class Upgrade(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        self.repo = support.repository(self)
        self.project = support.project(self, self.repo)

    def packet(self, with_report=True):
        git.run(self.repo, "checkout", "-q", "-b", "work/tests-a")
        (self.repo / "test_a.txt").write_text("test\n")
        if with_report:
            (self.repo / ".work-report.md").write_text("Status: done\n")
        commit = support.commit(self.repo, "tests")
        git.run(self.repo, "checkout", "-q", "main")
        return commit

    def ledger(self, packet):
        record = lambda item, status, **f: {"project": "p", "item": item, "kind": "queued", "brief": item, "summary": None,
                                            "depends": [], "stage": "implementation", "reasoning_effort": None,
                                            "held_by": None, "priority": 1, "status": status, "decompose": False,
                                            "hash": f"h-{item}", **f}
        return {
            "queue": {
                "p:tests-a": record("tests-a", "done", stage="test-contract", commit=packet),
                "p:landed": record("landed", "done", commit="abc"),
                "p:awaiting": record("awaiting", "blocked", decompose=True, report="r", depends=["`landed`.", "none"]),
                "p:stuck": record("stuck", "blocked", report="manager gave up", held_by="someone"),
                "p:split": record("split", "done", replaced_by=["landed"]),
                "p:fresh": record("fresh", "queued"),
            },
            "tasks": {
                "p:tests-a": task("p:tests-a", "item", "done", "x"),
                "p:landed": task("p:landed", "item", "done", "h-landed",
                                 acceptance={"commit": "abc", "worker_commit": "w", "via": "landing"}),
                "p:awaiting": task("p:awaiting", "item", "failed", "old-hash"),
                "p:decompose-awaiting": task("p:decompose-awaiting", "decompose", "done", "older-hash"),
                "p:stuck": task("p:stuck", "item", "failed", "old-hash"),
                "p:decompose-stuck": task("p:decompose-stuck", "decompose", "failed", "h-stuck"),
                "p:fresh": task("p:fresh", "item", "failed", "stale"),
                "p:garden-1": task("p:garden-1", "garden", "done", "health-hash"),
            },
        }

    def test_an_old_ledger_keeps_where_every_record_stands(self):
        packet = self.packet()
        upgraded = upgrade_ledger.upgrade(self.ledger(packet), [self.project])
        state.L.update(upgraded)
        stands = {k: queues.state(r) for k, r in upgraded["queue"].items()}
        self.assertEqual({k: s["status"] for k, s in stands.items()},
                         {"p:tests-a": "done", "p:landed": "done", "p:awaiting": "blocked", "p:stuck": "blocked",
                          "p:split": "replaced", "p:fresh": "queued"})
        self.assertTrue(stands["p:awaiting"]["decompose"], "a failed item still awaits its manager")
        self.assertFalse(stands["p:stuck"]["decompose"], "a finished decomposition still speaks for its item")
        self.assertEqual(upgraded["queue"]["p:landed"]["done"], {"at": 5, "commit": "abc", "via": "landing"})
        self.assertEqual(upgraded["queue"]["p:awaiting"]["depends"], ["landed"])
        self.assertEqual(upgraded["queue"]["p:stuck"]["held_by"], "user")
        self.assertEqual(upgraded["tasks"]["p:garden-1"]["health_hash"], "health-hash")
        for record in upgraded["queue"].values():
            self.assertFalse({"status", "decompose", "report", "hash", "commit"} & set(record))

    def test_a_packets_work_report_is_stripped_and_kept_reachable(self):
        packet = self.packet()
        upgraded = upgrade_ledger.upgrade(self.ledger(packet), [self.project])
        stripped = upgraded["queue"]["p:tests-a"]["done"]["commit"]
        self.assertNotEqual(stripped, packet)
        files = git.run(self.repo, "ls-tree", "-r", "--name-only", stripped).split()
        self.assertEqual(files, ["test_a.txt"])
        self.assertEqual(git.head(self.repo, "refs/cointos/archive/packets/tests-a"), stripped)
        again = upgrade_ledger.upgrade(copy.deepcopy(upgraded), [self.project])
        self.assertEqual(again, upgraded, "a second run changes nothing")

    def test_an_idle_worker_branch_drops_its_report_and_finishes_again(self):
        worker = support.queued(self.project, "build")
        support.running(worker, "worker-1")
        (Path(worker["worktree"]) / ".work-report.md").write_text("Status: done\n")
        (Path(worker["worktree"]) / "build.c").write_text("int build;\n")
        support.commit(worker["worktree"])
        worker.update(status="review", receipt={"run": "worker-1", "disposition": "complete", "summary": "s",
                                                "evidence": {}, "at": 1}, agent=None)
        upgraded = upgrade_ledger.upgrade(json.loads(json.dumps(state.L)), [self.project])
        moved = upgraded["tasks"][worker["id"]]
        self.assertEqual((moved["status"], moved["receipt"]), ("waiting", None))
        self.assertFalse((Path(worker["worktree"]) / ".work-report.md").exists())
        self.assertTrue(git.clean(worker["worktree"]))


if __name__ == "__main__":
    unittest.main()
