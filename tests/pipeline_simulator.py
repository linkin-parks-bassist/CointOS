"""Deterministic fault simulation of CointOS's actual orchestration functions.

Only environmental boundaries are replaced: Git's immutable commit DAG, command
results, durable writes, process cleanup and clock. Lifecycle/queue/admission/
landing code is production code. Real Git/HTTP replays must check this adapter.
This cannot judge whether an agent's product contract or implementation is good.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import copy
import json
import itertools
import io
import os
from pathlib import Path
import random
import runpy
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch

from cointos import frontier, api, contracts, daemon, git, lifecycle, queues, recovery, runs, spawner, state, tasks
from cointos import landing, opencode, keys, config, schema


class Crash(BaseException):
    """Process loss, distinct from a refused domain operation."""


class ObservationYield(BaseException):
    """Suspend a synchronous observer at its environmental polling boundary."""


class Simulation:
    faults = (
        "none", "duplicate", "lost_reply", "stale_run", "dirty_main",
        "switched_main", "dirty_worker", "dirty_candidate", "worker_moved",
        "main_moved", "candidate_moved", "test_failure", "test_timeout",
        "mutating_tests", "missing_packet", "tampered_packet", "git_failure",
        "crash_before_intent", "crash_after_intent", "crash_after_ref",
        "crash_before_settlement_save", "hold_during_test", "kill_during_test",
        "cancel_during_test", "failed_test_after_kill", "worker_blocked",
        "revision", "dependency_cycle", "missing_dependency", "held_dependency",
        "ledger_write_failure", "retired_after_publish", "hold_integrator",
        "worker_moved_during_test", "receipt_changed_during_test",
        "two_workers", "unmerged_main",
        "receipt_crash_before_save", "receipt_crash_after_save",
        "incorporate_cancel", "incorporate_hold", "incorporate_receipt_changed",
        "manager_unresolved",
        "adopt_live_worker", "adopt_missing_key", "adopt_dead_integrator",
        "adopt_live_integrator", "adopt_receipted_worker",
        "adopt_published_exhausted",
        "integration_resume_race",
        "repair_manager_blocked", "repair_manager_exhausted", "repair_origin_revision",
        "repair_unknown_dependency", "repair_dependency_cycle", "repair_explicit_hold",
        "repair_stale_before_admission", "repair_no_recursive_operator",
        "repair_superseded_periodic",
        "repair_prerequisite_arrived", "repair_obstruction_cleared",
        "repair_pending_graph_regression", "repair_human_cancelled",
        "repair_live_superseded", "repair_newer_failed", "repair_newer_pending",
        "repair_receipt_crash_before_save", "repair_receipt_crash_after_save",
        "namespace_maintenance_first", "namespace_queue_first", "namespace_cancelled_record",
        "observer_ambiguous_query", "observer_query_oserror", "observer_structured_error",
        "observer_terminal_tail",
        "observer_malformed_shapes", "producer_metadata_failure",
        "hidden_red_review", "hidden_red_main", "hidden_green_review", "hidden_rejected_review", "hidden_blocked_review",
        "hidden_validation_races", "hidden_save_replacement",
        "admission_namespace", "admission_key_failure", "admission_thread_failure",
        "admission_launch_artifacts",
        "authority_ledger", "authority_enrollment", "authority_namespace",
        "artifact_publication_race", "artifact_interrupted_server", "artifact_interrupted_exit",
        "qualified_dependencies", "migrate_qualified_dependencies",
    )

    def __init__(self):
        self.stack = contextlib.ExitStack()
        namespace = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='cointos-sim-keys-')))
        self.keyfile = namespace / 'keys.json'
        self.stack.enter_context(patch.object(keys, 'KEYS', self.keyfile))
        self.stack.enter_context(patch.dict(keys.OWNERS, {}, clear=True))
        self.stack.enter_context(patch.dict(keys.ISSUED, {}, clear=True))
        self.stack.enter_context(patch.object(keys, 'ENDED', set()))
        self.stack.enter_context(patch.dict(state.STARTUP, {}, clear=True))
        self.project = {"name": "sim", "path": "/sim/repo", "main_branch": "main",
                        "priority": 100, "enabled": True,
                        "test_policy": {"manifest": "tests/contracts.json", "protected": ["tests/**"]}}
        self.original = copy.deepcopy(state.L)
        self.original_config = copy.deepcopy(state.CONFIG)
        self.original_active = copy.deepcopy(state.ACTIVE)
        self.original_stopping = state.STOPPING.is_set()
        self.reconcile = lifecycle.reconcile
        self.tree_work = spawner.tree_work
        self.base_ledger = state.fresh({'paused': False})
        self.stack.enter_context(patch.dict(state.CONFIG, projects=[self.project], trees=[]))
        self.stack.enter_context(patch.object(tasks.names, "invent", lambda used: "Sim"))
        for module in (state, tasks, queues, lifecycle, landing, api, daemon, recovery, runs, spawner):
            if hasattr(module, "now"):
                self.stack.enter_context(patch.object(module, "now", lambda: self.clock))
            if hasattr(module, "log"):
                self.stack.enter_context(patch.object(module, "log", lambda *a, **k: None))
            if hasattr(module, "save"):
                self.stack.enter_context(patch.object(module, "save", self.save))
        self.stack.enter_context(patch.object(state.journal, "write", lambda *a, **k: None))
        self.stack.enter_context(patch.object(queues, "publish", lambda: None))
        self.stack.enter_context(patch.object(lifecycle, "clean_up", lambda t: None))
        self.stack.enter_context(patch.object(lifecycle.opencode, "stop", lambda *a, **k: None))
        self.stack.enter_context(patch.object(lifecycle.snapshots, "forget_owner", lambda *a, **k: None))
        self.stack.enter_context(patch.object(lifecycle.keys, "revoke", lambda *a, **k: None))
        self.stack.enter_context(patch.object(lifecycle.lanes, "cancel_agent", lambda *a, **k: None))
        self.stack.enter_context(patch.object(lifecycle.threading, "Thread"))
        self.stack.enter_context(patch.object(landing, "repository_lock", lambda r: contextlib.nullcontext()))
        for name, value in (("head", self.head), ("clean", self.clean),
                            ("contains", self.contains), ("changed", self.changed),
                            ("run", self.git_run), ("publish", self.publish)):
            self.stack.enter_context(patch.object(git, name, value))
        # The namespace fixture's committed answer and index have identical bytes.
        # Model only filesystem/Git reads; keep production eligibility active.
        result, read_text, exists = git.result, Path.read_text, Path.exists
        fixture = self.project['path'] + '/.knowledge/what/is/fixture.md'
        answer = 'A simulated canonical answer.\n'
        def git_result(repo, *args):
            if len(args) == 2 and args[0] == 'show' and args[1].endswith(':.knowledge/what/is/fixture.md'):
                commit = args[1].split(':', 1)[0]
                assert commit == '' or commit in self.parents
                return subprocess.CompletedProcess(args, 0, answer, '')
            return result(repo, *args)
        def canonical_text(path, *args, **kwargs):
            return answer if str(path) == fixture else read_text(path, *args, **kwargs)
        self.stack.enter_context(patch.object(git, 'result', git_result))
        self.stack.enter_context(patch.object(Path, 'read_text', canonical_text))
        self.stack.enter_context(patch.object(Path, 'exists', lambda path: True if str(path) == fixture else exists(path)))
        # These faults corrupt the composed landing packet, not the worker's edit history.
        self.stack.enter_context(patch.object(contracts, "stage_history", lambda *a: None))
        for name in ("packet_unchanged", "incorporated"):
            self.stack.enter_context(patch.object(contracts, name, self.packet))
        self.stack.enter_context(patch.object(contracts, "packet_check", self.packet_check))
        self.stack.enter_context(patch.object(contracts, "tests_landed", lambda *a: True))
        self.stack.enter_context(patch.object(contracts, "suite", self.suite))
        self.stack.enter_context(patch.object(spawner, "tree_work", lambda: []))
        self.stack.enter_context(patch.object(spawner, "periodic", lambda: []))
        self.stack.enter_context(patch.object(lifecycle, "reconcile", lambda: None))
        state.STOPPING.clear()

    def close(self):
        self.stack.close()
        state.ACTIVE.clear()
        state.ACTIVE.update(self.original_active)
        state.L.clear()
        state.L.update(self.original)
        state.CONFIG.clear()
        state.CONFIG.update(self.original_config)
        if self.original_stopping:
            state.STOPPING.set()
        else:
            state.STOPPING.clear()

    def node(self, parents=()):
        ref = f"{len(self.parents) + 1:040x}"
        self.parents[ref] = set(parents) | {p for x in parents for p in self.parents[x]}
        return ref

    def head(self, repo, ref="HEAD"):
        if ref == "HEAD":
            ref = self.worktrees[str(repo)]
        return self.refs.get(ref, ref) if ref in self.refs or ref in self.parents else self.missing(ref)

    @staticmethod
    def missing(ref):
        raise ValueError(f"missing Git artifact: {ref}")

    def clean(self, repo):
        return str(repo) not in self.dirty

    def changed(self, repo, before, after):
        # Each simulated node is a distinct committed artifact. Real Git's
        # empty/reverted-tree boundary is exercised by test_pre_stop_check.
        return [] if self.head(repo, before) == self.head(repo, after) else ['simulated-artifact']

    def contains(self, repo, commit, branch):
        commit = self.head(repo, commit)
        target = self.head(repo, branch)
        return target == commit or commit in self.parents[target]

    def git_run(self, repo, *args):
        if args == ('ls-tree', '-r', '--name-only', 'main', '.knowledge'):
            assert str(repo) == self.project['path']
            return '.knowledge/what/is/fixture.md\n'
        if len(args) == 2 and args[0] in ('rev-parse', 'show') and ':' in args[1]:
            commit, path = args[1].split(':', 1)
            assert commit in self.parents and path == '.knowledge/what/is/the/plan.md'
            return 'fixture-plan-' + commit if args[0] == 'rev-parse' else 'No remaining approved work.\n'
        if len(args) == 2 and args[0] == 'rev-parse' and args[1].endswith('^{tree}'):
            # This model assigns one content state to each node; real-Git regressions
            # separately cover different commits sharing an unchanged tree.
            commit = args[1][:-len('^{tree}')]
            assert commit in self.parents
            return commit
        if args[:2] == ("branch", "--show-current"):
            return self.worktrees[str(repo)]
        if args[:2] == ("merge", "--ff-only"):
            if "git_failure" in self.fault:
                raise ValueError("simulated Git write failure")
            self.refs["main"] = args[2]
            self.trace.append("advance-main")
            if "crash_after_ref" in self.fault:
                raise Crash()
            return ""
        if args[:2] == ("rev-list", "--count"):
            return "1"
        raise AssertionError((repo, args))

    def publish(self, repo, main, commit, expected):
        if self.refs[main] != expected or not self.contains(repo, expected, commit):
            raise ValueError("main changed; review and retry publication")
        if "git_failure" in self.fault:
            raise ValueError("simulated Git write failure")
        if str(repo) in self.dirty and self.worktrees[str(repo)] == main:
            self.refs["draft"] = expected
            self.worktrees[str(repo)] = "draft"
        self.refs[main] = commit
        self.trace.append("advance-main")
        if "retired_after_publish" in self.fault:
            for task in (self.worker, self.integration):
                self.refs.pop(task["branch"])
                self.worktrees.pop(task["worktree"])
        if self.fault.intersection(("crash_after_ref", "retired_after_publish")):
            raise Crash()
        return {"commit": commit}

    def packet(self, *args):
        if self.fault.intersection(("missing_packet", "tampered_packet")):
            raise ValueError("protected test tree does not match the accepted packet")

    def packet_check(self, *args):
        self.packet()
        return {"packet_tests": 1}

    def save(self):
        self.saves += 1
        if "receipt_crash_before_save" in self.fault:
            raise Crash()
        if "receipt_crash_after_save" in self.fault:
            self.durable = copy.deepcopy(state.L)
            raise Crash()
        if "ledger_write_failure" in self.fault and self.saves == 1:
            raise ValueError("simulated disk full before intent durability")
        if "crash_before_intent" in self.fault and self.saves == 1:
            raise Crash()
        if "crash_before_settlement_save" in self.fault and self.saves == 2:
            raise Crash()
        if any(f.startswith("crash_") for f in self.fault) or "retired_after_publish" in self.fault:
            self.durable = copy.deepcopy(state.L)
        if "crash_after_intent" in self.fault and self.saves == 1:
            raise Crash()

    def suite(self, *args):
        self.trace.append("validate")
        w, i = self.worker, self.integration
        for fault in self.order:
            self.trace.append('test-event:' + fault)
            if fault == 'main_moved':
                self.refs['main'] = self.node([self.refs['main']])
            elif fault == 'candidate_moved':
                self.refs[i['branch']] = self.node([self.candidate])
            elif fault == 'worker_moved_during_test':
                self.refs[w['branch']] = self.node([self.refs[w['branch']]])
            elif fault == 'receipt_changed_during_test':
                w['receipt']['summary'] = 'different submitted work'
            elif fault == 'hold_integrator':
                i['admission_hold'] = 'user'
            elif fault == 'hold_during_test':
                # A concurrent control targeting an already-cancelled record is
                # a refused request, not a scheduler transition or acceptance.
                if w['record'] in queues.records():
                    lifecycle.hold(w['record'], 'user')
            elif fault in ('kill_during_test', 'failed_test_after_kill') and i['agent']:
                lifecycle.kill(i['agent'])
            elif fault == 'cancel_during_test' and w['record'] in queues.records():
                lifecycle.cancel([w['record']], 'user', 'withdrawn')
            elif fault in ('test_timeout', 'mutating_tests'):
                raise ValueError('test boundary failed: ' + fault)
        caused = self.fault.intersection(("test_failure", "failed_test_after_kill")) or any(
            f.startswith('hidden_') for f in self.fault)
        if 'hidden_green_review' in self.fault:
            return {'suite': 1, 'failed': 0, 'red_on_main': 0}, []
        if 'hidden_red_main' in self.fault:
            return {'suite': 1, 'failed': 1, 'red_on_main': 1}, []
        return {"suite": 1, "failed": int(bool(caused)), "red_on_main": 0}, [(["check"], "assertion failed", "test source")] if caused else []

    def start(self, t, run):
        self.bind_contract(t)
        self.worktrees[t["worktree"]] = t["branch"]
        self.refs.setdefault(t["branch"], self.refs["main"])
        if t['kind'] == 'item' and not t.get('base_commit'):
            t['base_commit'] = self.refs['main']
        lifecycle.start(t, run)
        state.L["agents"][run] = {"id": run, "task": t["id"], "class": "background",
                                  "engaged": True, "last_activity": self.clock,
                                  "thoughts": 1, "started_at": self.clock}

    def bind_contract(self, task):
        """Supply independent acceptance to the modeled implementation fixture."""
        record = queues.records().get(task.get('record'))
        if task.get('stage') not in schema.TESTED or record is None:
            return
        project = tasks.place(task)
        if any((queues.records().get(f"{task['place']}:{name}") or {}).get('stage') == 'test-contract'
               for name in record['depends']):
            return
        name = 'fixture-tests'
        key = f"{task['place']}:{name}"
        if key not in queues.records():
            queues.add(project, 'queued', name, 'Independent fixture contract\nRelies on: existing_api',
                       stage='test-contract')
            queues.finish(queues.records()[key], commit=self.refs['main'], via='tests')
        record['depends'].append(name)

    def native_startup(self, command, pids):
        """Only the native unit-show boundary; real key load and attestation run."""
        assert command[:3] == ['systemctl', '--user', 'show'], command
        run = command[3].removeprefix('cointos-agent-').removesuffix('.service')
        assert run in pids, command
        return subprocess.CompletedProcess(command, 0,
            f'ActiveState=active\nMainPID={pids[run]}\nInvocationID=sim-{run}\nLoadState=loaded\n', '')

    def reset(self, fault, seed):
        self.keyfile.write_text(json.dumps({'coin': 'sim-coin', 'agents': {}}))
        keys.OWNERS.clear()
        keys.ISSUED.clear()
        keys.ENDED.clear()
        state.STARTUP.clear()
        self.clock = 1000.0 + seed
        state.L.clear()
        state.L.update(copy.deepcopy(self.base_ledger))
        state.ACTIVE["landings"] = 0
        self.order = [fault] if isinstance(fault, str) else list(fault)
        self.fault = set(self.order)
        self.trace, self.saves = sorted(self.fault), 0
        self.parents, self.refs, self.worktrees, self.dirty = {}, {}, {}, set()
        self.refs["main"] = self.node()
        self.worktrees[self.project["path"]] = "main"
        hidden = any(f.startswith('hidden_') for f in self.fault)
        queues.add(self.project, "queued", "a", "Relies on: existing_api\nImplement A" if hidden else "Implement A",
                   stage="test-contract" if hidden else "implementation")
        w = tasks.create("item", self.project, "a", "Implement A", [4], item="a", record_version=1)
        self.worker = w
        self.start(w, "worker")
        self.refs[w["branch"]] = self.node([self.refs["main"]])
        # Checked packet result is an environmental oracle, not a second lifecycle.
        blocked = self.fault.intersection(('worker_blocked', 'manager_unresolved')) or any(
            f.startswith('repair_') for f in self.fault)
        disposition = "blocked" if blocked else "complete"
        checked = {"commit": self.head(w["worktree"]), "tests": landing.tests_of(w), "packet_tests": 1}
        if hidden:
            checked['passing'] = 'hidden_green_review' in self.fault
        with patch.object(contracts, 'contracts', return_value=[]) if hidden else contextlib.nullcontext():
            receipt = lifecycle.submit(w["id"], "worker", disposition, "result", checked)
        if self.fault.intersection(("duplicate", "lost_reply")):
            assert lifecycle.submit(w["id"], "worker", disposition, "result", checked) == receipt
        state.L["agents"].pop("worker")
        self.integration = None
        if blocked:
            return
        i = tasks.create("integrate", self.project, "integrate-a", "Implement A", [2], item="a", worker=w["id"])
        self.integration = i
        self.start(i, "integrator")
        self.candidate = self.node([self.refs["main"], checked["commit"]])
        self.refs[i["branch"]] = self.candidate
        self.durable = copy.deepcopy(state.L)
        if self.fault.intersection(("dirty_main", "unmerged_main")):
            self.dirty.add(self.project["path"])
        if "switched_main" in self.fault:
            self.worktrees[self.project["path"]] = "user-branch"
        if "dirty_worker" in self.fault:
            self.dirty.add(w["worktree"])
        if "dirty_candidate" in self.fault:
            self.dirty.add(i["worktree"])
        if "worker_moved" in self.fault:
            self.refs[w["branch"]] = self.node([checked["commit"]])

    def invariants(self):
        for t in state.L["tasks"].values():
            a = t.get("acceptance")
            if a and a['via'] == 'tests':
                assert t['stage'] == 'test-contract' and t['status'] == 'done'
                assert t['receipt']['disposition'] == 'complete'
                assert a['worker_commit'] == t['receipt']['evidence']['commit']
                assert queues.records()[t['record']]['done']['commit'] == a['commit']
            if a and a["via"] == "landing":
                assert t["status"] == "done", "accepted worker not done"
                assert t["receipt"]["disposition"] == "complete", "blocked work accepted"
                assert a["worker_commit"] == t["receipt"]["evidence"]["commit"], "wrong worker commit"
                assert self.contains(self.project["path"], a["commit"], "main"), "acceptance absent from main"
                assert queues.records()[t["record"]]["done"]["commit"] == a["commit"], "queue acceptance diverged"

    def trial(self, fault, seed):
        self.reset(fault, seed)
        w = self.worker
        if 'migrate_qualified_dependencies' in self.fault:
            return self.migration_dependency_trial(seed)
        if 'qualified_dependencies' in self.fault:
            return self.qualified_dependency_trial(seed)
        if any(f.startswith('authority_') for f in self.fault):
            return self.authority_trial()
        if any(f.startswith('admission_') for f in self.fault):
            return self.admission_trial()
        if any(f.startswith('hidden_') for f in self.fault):
            return self.hidden_trial()
        if 'producer_metadata_failure' in self.fault:
            return self.producer_failure_trial()
        if any(f.startswith('artifact_') for f in self.fault):
            return self.artifact_trial()
        if any(f.startswith('observer_') for f in self.fault):
            return self.observer_trial()
        if any(f.startswith('namespace_') for f in self.fault):
            return self.namespace_trial()
        if any(f.startswith('repair_') for f in self.fault):
            return self.repair_trial()
        if "two_workers" in self.fault:
            return self.parallel_trial()
        if 'integration_resume_race' in self.fault:
            return self.integration_resume_trial()
        if any(f.startswith('adopt_') for f in self.fault):
            return self.adoption_trial()
        if self.fault.intersection(('receipt_crash_before_save', 'receipt_crash_after_save')):
            return self.receipt_trial()
        if any(f.startswith('incorporate_') for f in self.fault):
            return self.incorporation_trial()
        if self.fault.intersection(('worker_blocked', 'manager_unresolved')):
            assert not spawner.integrations(), "blocked worker consumed an unnecessary integrator run"
            manager = spawner.next_task()
            assert manager and manager["kind"] == "operator", "blocked worker stranded without recovery controller"
            assert spawner.next_task() is manager, "duplicate recovery controller"
            self.start(manager, "manager")
            if 'manager_unresolved' in self.fault:
                lifecycle.submit(manager['id'], 'manager', 'blocked', 'verified contract decision required')
                state.L['agents'].pop('manager')
                queues.add(self.project, 'queued', 'dependent', 'Build dependent\nDepends on: a', stage='skeleton')
                spawner.refresh()
                alerts = copy.deepcopy(state.L['alerts'])
                durable = copy.deepcopy(state.L)
                state.L.clear()
                state.L.update(state.fresh(durable))
                for _ in range(3):
                    spawner.refresh()
                    assert spawner.next_task() is None, 'unchanged unresolved manager looped'
                assert state.L['alerts'] == alerts, 'restart repeated unchanged dependency alert'
                assert not queues.records()[w['record']].get('done')
                return 'unresolved-controller-retained'
            lifecycle.revise(w["record"], manager['id'], "verified mismatch",
                             "Summary: Implement the verified correction to this assignment\nImplement clarified A",
                             dependency_ids=queues.records()[w['record']]['depends'])
            lifecycle.submit(manager["id"], "manager", "complete", "assignment repaired")
            state.L["agents"].pop("manager")
            assert spawner.next_task() is w, "manager repair did not release worker"
            return "direct-controller-repair"
        if self.fault.intersection(("dependency_cycle", "missing_dependency", "held_dependency", "revision")):
            return self.queue_trial(fault)
        observed = set(self.fault)
        w, i = self.worker, self.integration
        before_bundle = copy.deepcopy(w.get("bundled", []))
        try:
            landing.land(i["id"], self.candidate, "old-run" if "stale_run" in self.fault else "integrator")
        except Crash:
            state.L.clear()
            state.L.update(copy.deepcopy(self.durable))
            self.worker, self.integration = state.L["tasks"][w["id"]], state.L["tasks"][i["id"]]
            state.ACTIVE["landings"] = 0
            self.trace.append("reload-durable-ledger")
        except ValueError as error:
            self.trace.append(str(error))
        self.fault = set()
        self.order = []
        lifecycle.recover_landings()
        self.invariants()
        w, i = self.worker, self.integration
        if observed.intersection(("hold_during_test", "hold_integrator")) and w.get("acceptance"):
            raise AssertionError("accepted held work")
        if "failed_test_after_kill" in observed and w.get("bundled", []) != before_bundle:
            raise AssertionError("stale validation mutated worker")
        if "test_failure" in observed and w["status"] == "waiting":
            assert w["status"] == "waiting" and not w.get("acceptance")
            return "returned-test-failure"
        if observed.intersection(("cancel_during_test", "kill_during_test", "failed_test_after_kill")) and i["agent"] != "integrator":
            return "refused-control-race"
        # After transient faults cease, exact accepted work must settle without a new model verdict.
        self.fault = set()
        self.dirty.clear()
        i["admission_hold"] = None
        if queues.records()[w["record"]].get("held_by"):
            lifecycle.unhold(w["record"], "user")
        self.worktrees[self.project["path"]] = "main"
        if not w.get("acceptance"):
            self.refs[w["branch"]] = w["receipt"]["evidence"]["commit"]
            self.candidate = self.node([self.refs["main"], self.refs[w["branch"]]]) if not self.contains(
                self.project["path"], self.refs["main"], self.candidate) else self.candidate
            self.refs[i["branch"]] = self.candidate
            landing.land(i["id"], self.candidate, i["agent"])
        a = copy.deepcopy(w["acceptance"])
        assert landing.land(i["id"], a["commit"], "stale-replay")["commit"] == a["commit"]
        assert w["acceptance"] == a
        self.invariants()
        return "landed"

    def queue_trial(self, fault):
        w = self.worker
        if "revision" in self.fault:
            self.integration["status"] = "waiting"
            state.L["agents"].pop("integrator")
            lifecycle.revise(w["record"], "user", "clarified", "Implement revised A")
            assert w["status"] == "waiting" and w["receipt"] is None
            assert w["record_version"] == 2 and not spawner.runnable(self.integration, {})
            return "revised"
        record = queues.records()[w["record"]]
        if "dependency_cycle" in self.fault:
            record["depends"] = ["a"]
        elif "missing_dependency" in self.fault:
            record["depends"] = ["missing"]
        else:
            queues.add(self.project, 'queued', 'prerequisite', 'Expose B', stage='skeleton')
            prerequisite = tasks.create('item', self.project, 'prerequisite', 'Expose B', [4],
                                        item='prerequisite', record_version=1)
            record['depends'] = ['prerequisite']
            lifecycle.hold(prerequisite['record'], 'user')
            ready = queues.readiness(queues.live('sim'), queues.landed('sim'))
            assert ready['a'] != 'ready' and not spawner.runnable(prerequisite, {'sim': ready})
            lifecycle.unhold(prerequisite['record'], 'user')
            ready = queues.readiness(queues.live('sim'), queues.landed('sim'))
            assert spawner.runnable(prerequisite, {'sim': ready}), 'released prerequisite stranded'
            return "held"
        ready = queues.readiness(queues.live("sim"), queues.landed("sim"))
        assert ready["a"] not in ("ready", "waiting")
        return "invalid-dependency-reported"

    def namespace_trial(self):
        """Queue proposals and scheduler factories share one durable task-ID space."""
        state.L['tasks'].clear()
        state.L['agents'].clear()
        queues.records().clear()
        state.L['paused'] = False
        tree = {**self.project, 'tree': '.knowledge'}
        health = {'brown': 1, 'yellow': 0, 'leaves': ['brown\tlocal:what/is/fixture.md'],
                  'hash': 'fixture', 'inventory': ['what/is/fixture.md']}
        body = {'project': 'sim', 'name': 'garden-1', 'brief': 'Implement useful queued work', 'stage': 'implementation'}
        with patch.dict(state.CONFIG, trees=[tree]), \
             patch.object(spawner, 'tree_work', self.tree_work), \
             patch.object(spawner, 'tree_health', return_value=health):
            if 'namespace_maintenance_first' in self.fault:
                maintenance = spawner.next_task()
                assert maintenance['kind'] == 'garden' and maintenance['id'] == 'sim:garden-1'
                self.start(maintenance, 'gardener')
                try:
                    api.dispatch('queue', body)
                except ValueError:
                    pass
                else:
                    raise AssertionError('new queue record reused live maintenance task identity')
                assert state.L['tasks'][maintenance['id']] is maintenance and maintenance['agent'] == 'gardener'
                assert not queues.records()
                return 'live-maintenance-identity-preserved'
            assert api.dispatch('queue', body)['item'] == 'garden-1'
            maintenance = spawner.next_task()
            assert maintenance['kind'] == 'garden' and maintenance['id'] != 'sim:garden-1', 'maintenance factory reused queued identity'
            self.start(maintenance, 'gardener')
            api.dispatch('cancel', {'items': [maintenance['id']], 'reason': 'isolated maintenance fixture completed'})
        worker = spawner.next_task()
        assert worker['kind'] == 'item' and worker['id'] == 'sim:garden-1', 'maintenance stranded wanted queue work'
        assert state.L['tasks'][maintenance['id']] is maintenance, 'queue dispatch overwrote maintenance task'
        assert api.dispatch('queue', body)['item'] == 'garden-1', 'identical proposal retry was refused'
        if 'namespace_cancelled_record' in self.fault:
            api.dispatch('cancel', {'items': [worker['id']], 'reason': 'user withdrew this assignment'})
            assert worker.get('cancelled') and worker['record'] not in queues.records()
            try:
                api.dispatch('queue', body)
            except ValueError:
                pass
            else:
                raise AssertionError('new proposal reused cancelled task identity')
            assert state.L['tasks'][worker['id']] is worker and worker.get('cancelled')
            return 'cancelled-task-identity-preserved'
        api.dispatch('revise', {'item': worker['id'], 'reason': 'clarified useful work', 'brief': body['brief']})
        assert state.L['tasks'][worker['id']] is worker and worker['record_version'] == 1
        assert api.dispatch('queue', body)['item'] == 'garden-1', 'current identical revised proposal was refused'
        self.worker = worker
        self.start(worker, 'namespace-worker')
        submitted = self.node([self.refs['main']])
        self.refs[worker['branch']] = submitted
        lifecycle.submit(worker['id'], 'namespace-worker', 'complete', 'useful namespace-safe implementation',
                         {'commit': submitted, 'tests': landing.tests_of(worker), 'packet_tests': 1})
        state.L['agents'].pop('namespace-worker')
        self.integration = integration = spawner.next_task()
        self.start(integration, 'namespace-integrator')
        self.candidate = self.node([self.refs['main'], submitted])
        self.refs[integration['branch']] = self.candidate
        landing.land(integration['id'], self.candidate, 'namespace-integrator')
        self.invariants()
        return 'queue-namespace-safe-and-landed'

    def parallel_trial(self):
        """Two reviewed workers share one accepted ref; stale candidates must rebase."""
        a, integration = self.worker, self.integration
        queues.add(self.project, 'queued', 'b', 'Implement B', stage='implementation')
        b = tasks.create('item', self.project, 'b', 'Implement B', [4], item='b', record_version=1)
        self.start(b, 'worker-b')
        submitted = self.node([self.refs['main']])
        self.refs[b['branch']] = submitted
        lifecycle.submit(b['id'], 'worker-b', 'complete', 'B ready', {'commit': submitted, 'tests': landing.tests_of(b)})
        state.L['agents'].pop('worker-b')
        assert not spawner.integrations(), 'a second integration bypassed project serialization'
        landing.land(integration['id'], self.candidate, 'integrator')
        options = spawner.integrations()
        assert len(options) == 1, 'completed integration stranded another reviewed worker'
        second = options[0][1]()
        assert second['worker'] == b['id']
        self.start(second, 'integrator-b')
        stale = self.node([submitted])
        self.refs[second['branch']] = stale
        try:
            landing.land(second['id'], stale, 'integrator-b')
        except ValueError:
            pass
        else:
            raise AssertionError('stale second candidate overwrote first acceptance')
        fresh = self.node([self.refs['main'], submitted])
        self.refs[second['branch']] = fresh
        landing.land(second['id'], fresh, 'integrator-b')
        assert a['acceptance'] and b['acceptance']
        self.invariants()
        return 'serialized-two-workers'

    def integration_resume_trial(self):
        """A released reviewer must wait for another reviewer of its project."""
        a, first = self.worker, self.integration
        lifecycle.kill('integrator')
        assert not spawner.runnable(first, {}), 'held integration admitted'
        queues.add(self.project, 'queued', 'b', 'Implement B', stage='implementation')
        b = tasks.create('item', self.project, 'b', 'Implement B', [4], item='b', record_version=1)
        self.start(b, 'worker-b')
        submitted = self.node([self.refs['main']])
        self.refs[b['branch']] = submitted
        lifecycle.submit(b['id'], 'worker-b', 'complete', 'B ready', {'commit': submitted, 'tests': landing.tests_of(b)})
        state.L['agents'].pop('worker-b')
        second = spawner.next_task()
        assert second['kind'] == 'integrate' and second['worker'] == b['id'], 'held reviewer stranded B'
        self.start(second, 'integrator-b')
        assert spawner.runnable(second, {}), 'running integration blocked itself'
        other_project = {**self.project, 'name': 'other', 'path': '/other/repo'}
        with patch.dict(state.CONFIG, projects=[self.project, other_project]):
            queues.add(other_project, 'queued', 'c', 'Implement C', stage='implementation')
            other_worker = tasks.create('item', other_project, 'c', 'Implement C', [4], item='c')
            other_worker['status'] = 'review'
            other_review = tasks.create('integrate', other_project, 'integrate-c', 'Review C', [2],
                                        item='c', worker=other_worker['id'])
            assert spawner.runnable(other_review, {}), 'one project blocked another project'
            # This scenario drains A/B only; C exists to check cross-project admission.
            state.L['tasks'].pop(other_review['id'])
            state.L['tasks'].pop(other_worker['id'])
            queues.records().pop('other:c')
        lifecycle.resume_task(first['id'])
        assert spawner.next_task() is None, 'released integration bypassed project serialization'
        candidate = self.node([self.refs['main'], submitted])
        self.refs[second['branch']] = candidate
        landing.land(second['id'], candidate, 'integrator-b')
        assert spawner.next_task() is first, 'completed reviewer stranded released integration'
        self.start(first, 'integrator-a-resumed')
        candidate = self.node([self.refs['main'], a['receipt']['evidence']['commit']])
        self.refs[first['branch']] = candidate
        landing.land(first['id'], candidate, 'integrator-a-resumed')
        self.invariants()
        assert a.get('acceptance') and b.get('acceptance')
        return 'serialized-resumed-review'

    def migration_dependency_trial(self, seed):
        """Actual stopped-ledger migration canonicalizes spelling, never authority or graph."""
        rng = random.Random(seed)
        migration = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/upgrade-ledger'),
                                   run_name='pipeline_simulator_dependency_upgrade')
        upgrade = migration['upgrade']
        aliases = ['sim:accepted', 'accepted']
        rng.shuffle(aliases)
        # Current factories supply full queue/task/run schemas. Only stored spellings
        # are historical: the upgrader receives no registry or real worktree paths.
        queues.add(self.project, 'queued', 'accepted', 'Accepted prerequisite')
        queues.finish(queues.records()['sim:accepted'], commit=self.refs['main'], via='landing')
        record = queues.records()['sim:a']
        record.update(version=4, held_by='user', depends=aliases,
                      brief='Summary: retain reviewed work and exact product instructions\r\n'
                            'Depends on: ' + ', '.join(aliases) + '\r\n'
                            'Keep this exact assignment text.\r\n'
                            '**Depends on:** sim:accepted\r\n')
        self.worker['record_version'] = 4
        self.integration['admission_hold'] = 'explicit user integration hold'
        self.integration['session'] = 'retained-integrator-session'
        for name, needed in [('unknown', 'forward'), ('cycle-left', 'cycle-right'), ('cycle-right', 'cycle-left')]:
            queues.add(self.project, 'queued', name, 'Retain graph boundary')
            queues.records()['sim:' + name].update(version=4, depends=['sim:' + needed],
                                                  brief='Depends on: sim:' + needed + '\nKeep graph boundary.')
        effects = []
        def refuse_git(*args, **kwargs):
            effects.append(args)
            raise AssertionError('dependency migration attempted a Git effect')
        with tempfile.TemporaryDirectory(prefix='cointos-sim-upgrade-') as temporary:
            # All migration-owned artifact probes stay inside an absent disposable
            # namespace. Nothing can discover an installed or project worktree.
            for task in state.L['tasks'].values():
                task['worktree'] = str(Path(temporary) / task['id'].replace(':', '-'))
            before = copy.deepcopy(state.L)
            with patch.dict(upgrade.__globals__, git=refuse_git):
                migrated = upgrade(copy.deepcopy(before), [])
                assert migrated['tasks'] == before['tasks'], 'migration changed task/run/receipt/hold authority'
                assert migrated['agents'] == before['agents'], 'migration changed live run ownership'
                assert {key: value for key, value in migrated.items() if key != 'queue'} == {
                    key: value for key, value in before.items() if key != 'queue'}, 'migration changed retained ledger authority'
                assert migrated['queue']['sim:accepted'] == before['queue']['sim:accepted'], 'accepted prerequisite changed'
                for key, old in before['queue'].items():
                    current = migrated['queue'][key]
                    assert {k: v for k, v in current.items() if k not in ('brief', 'depends')} == {
                        k: v for k, v in old.items() if k not in ('brief', 'depends')}, 'spelling migration revised wanted work'
                    if key != 'sim:accepted':
                        assert set(queues.depends(current['brief'])) == set(current['depends']), 'brief and graph disagree'
                brief = migrated['queue']['sim:a']['brief']
                assert brief == ('Summary: retain reviewed work and exact product instructions\r\n'
                                 'Depends on: accepted\r\nKeep this exact assignment text.\r\n'
                                 'Depends on: accepted\r\n'), 'migration changed metadata rows or unrelated assignment bytes'
                assert upgrade(copy.deepcopy(migrated), []) == migrated, 'migration is not idempotent'
                # One invalid record after valid records must refuse the WHOLE input
                # before any mutation or Git effect, including secondary metadata.
                invalid = ['foreign:accepted', 'sim:Accepted', 'sim:accepted:extra', 'sim:', ':accepted', 'sim:none']
                rng.shuffle(invalid)
                secondary = {'secondary-conflict': 'sim:different', 'secondary-foreign': 'foreign:accepted',
                             'secondary-malformed': 'sim:accepted:extra'}
                for name in invalid + list(secondary):
                    damaged = copy.deepcopy(before)
                    victim = damaged['queue']['sim:cycle-right']
                    if name in secondary:
                        victim['brief'] += '\nDepends on: ' + secondary[name]
                    else:
                        victim.update(depends=[name], brief='Depends on: ' + name + '\nRetain instruction.')
                    unchanged = copy.deepcopy(damaged)
                    try:
                        upgrade(damaged, [])
                    except ValueError:
                        pass
                    else:
                        raise AssertionError('invalid stored dependency metadata was migrated: ' + name)
                    assert damaged == unchanged, 'migration refusal partially rewrote saved authority'
                assert not effects, 'migration made an environmental Git call'
            state.L.clear()
            state.L.update(migrated)
            readiness = queues.readiness(queues.live('sim'), queues.landed('sim'))
            assert readiness['a'] == 'ready', 'accepted qualified prerequisite remained blocked after migration'
            assert readiness['unknown'] == 'depends on unknown forward', 'migration fabricated missing acceptance'
            assert all('cycle' in readiness[name] for name in ('cycle-left', 'cycle-right')), 'migration broke cycle detection'
        self.trace.append('stored-qualified-graph-migrated-with-authority-retained')
        return 'qualified-ledger-migrated-with-authority-retained'

    def qualified_dependency_trial(self, seed):
        """Qualified same-project API names belong to the existing local graph."""
        rng = random.Random(seed)
        aliases = ['sim:a', 'a']
        rng.shuffle(aliases)
        api.dispatch('queue', {'project': 'sim', 'name': 'qualified', 'kind': 'queued',
                              'brief': 'Depends on: ' + ', '.join(aliases + ['sim:forward']) + '\nImplement after the declared prerequisites.'})
        record = state.L['queue']['sim:qualified']
        assert record['depends'] == ['a', 'forward']
        assert queues.line(record['brief'], 'Depends on') == 'a, forward'
        readiness = lambda: queues.readiness(queues.live('sim'), queues.landed('sim'))['qualified']
        assert readiness() == 'depends on unknown forward'
        api.dispatch('queue', {'project': 'sim', 'name': 'forward', 'kind': 'queued', 'brief': 'Make the prerequisite'})
        assert readiness() == 'waiting'
        api.dispatch('revise', {'item': 'sim:qualified', 'reason': 'Correct prerequisites',
                               'brief': 'Depends on: sim:forward, forward\nUse the corrected prerequisite.'})
        assert record['depends'] == ['forward']
        assert queues.line(record['brief'], 'Depends on') == 'forward'
        before = copy.deepcopy(state.L)
        invalid = rng.choice(['foreign:forward', 'sim:forward:extra', 'sim:', ':forward'])
        try:
            api.dispatch('revise', {'item': 'sim:qualified', 'reason': 'Check identity',
                                   'brief': 'Depends on: ' + invalid + '\nThis must be refused.'})
        except ValueError:
            pass
        else:
            raise AssertionError('foreign or malformed dependency was accepted')
        assert state.L == before, 'refused dependency changed queue/task/run authority'
        queues.finish(state.L['queue']['sim:forward'])
        assert readiness() == 'ready'
        self.invariants()
        return 'qualified-local-dependencies-ready'

    def authority_trial(self):
        """Disposable durable inputs refuse erasure before resuming useful admission."""
        live_before = copy.deepcopy(state.L)
        with tempfile.TemporaryDirectory(prefix='cointos-sim-authority-') as temporary:
            directory = Path(temporary)
            ledger = directory / 'ledger.json'
            operational = directory / 'cointos.json'
            registry = directory / 'projects.json'
            operational.write_text(json.dumps({'trees': []}))
            enrolled = {'projects': [{'name': 'sim', 'path': self.project['path'], 'main_branch': 'main'}]}
            registry.write_text(json.dumps(enrolled))
            if 'authority_ledger' in self.fault:
                valid = copy.deepcopy(state.L)
                valid['tasks'][self.worker['id']]['validating'] = True
                invalid = [None, [], 3, 'ledger']
                for field in ('tasks', 'queue', 'agents', 'snapshots', 'system_contexts',
                              'dependency_problems', 'check_incidents', 'cadence', 'coin'):
                    invalid.append({**copy.deepcopy(valid), field: []})
                for field in ('messages', 'history', 'alerts'):
                    invalid.append({**copy.deepcopy(valid), field: {}})
                for field in ('tasks', 'agents', 'queue', 'snapshots'):
                    invalid.append({**copy.deepcopy(valid), field: {'broken': None}})
                for previous in invalid:
                    ledger.write_text(json.dumps(previous))
                    loaded = config.read_owned_json(ledger, {})
                    untouched = copy.deepcopy(loaded)
                    try:
                        daemon.restore(loaded)
                    except ValueError:
                        pass
                    else:
                        raise AssertionError('invalid ledger was restored as current authority')
                    assert loaded == untouched, 'ledger validation mutated retained input before refusal'
                    assert state.L == live_before, 'invalid ledger replaced current task authority'
                for contents in ('{', '{"tasks":{},"tasks":{"lost":{}}}', json.dumps(valid)):
                    ledger.write_text(contents)
                    permission_fault = contents == json.dumps(valid)
                    if permission_fault:
                        ledger.chmod(0)
                    try:
                        try:
                            config.read_owned_json(ledger, {})
                        except (ValueError, OSError):
                            pass
                        else:
                            raise AssertionError('malformed or unreadable ledger was silently initialized')
                    finally:
                        ledger.chmod(0o600)
                    assert ledger.read_text() == contents and state.L == live_before
                ledger.write_text(json.dumps(valid))
                restored = state.fresh(config.read_owned_json(ledger, {}))
                assert self.worker['id'] in restored['tasks'] and restored['queue'] == state.L['queue']
                assert not restored['tasks'][self.worker['id']].get('validating')
            if 'authority_enrollment' in self.fault:
                invalid = ['{', 'null', '[]', '{}', '{"projects":null}', '{"projects":{}}',
                           '{"projects":[null]}', '{"projects":[{"name":7,"path":"/sim"}]}',
                           '{"projects":[{"name":"sim","path":7}]}',
                           '{"projects":[],"projects":[{"name":"lost","path":"/sim"}]}']
                for contents in [*invalid, json.dumps(enrolled)]:
                    registry.write_text(contents)
                    permission_fault = contents == json.dumps(enrolled)
                    if permission_fault:
                        registry.chmod(0)
                    try:
                        try:
                            config.load(operational, registry)
                        except (ValueError, OSError):
                            pass
                        else:
                            raise AssertionError('invalid enrollment silently changed managed projects')
                    finally:
                        registry.chmod(0o600)
                    assert registry.read_text() == contents and state.L == live_before
                registry.write_text(json.dumps(enrolled))
                for contents in ('null', '[]', '{'):
                    operational.write_text(contents)
                    try:
                        config.load(operational, registry)
                    except (ValueError, OSError):
                        pass
                    else:
                        raise AssertionError('invalid operational authority was loaded')
                operational.write_text(json.dumps({'trees': []}))
                assert config.load(operational, registry)['projects'] == enrolled['projects']
            if 'authority_namespace' in self.fault:
                target = directory / 'valid.json'
                target.write_text('{"retained":"authority"}')
                (directory / 'symlink').symlink_to(target)
                (directory / 'dangling').symlink_to(directory / 'absent-target')
                os.mkfifo(directory / 'fifo')
                (directory / 'nonregular').mkdir()
                child = '''import json,sys
from pathlib import Path
from cointos.config import read_owned_json
root=Path(sys.argv[1]); refused=[]
for name in ('symlink','dangling','fifo','nonregular'):
    try: read_owned_json(root/name,{})
    except (OSError,ValueError): refused.append(name)
    else: raise AssertionError('nonregular ownership path accepted: '+name)
assert read_owned_json(root/'missing',{'absent':True})=={'absent':True}
assert read_owned_json(root/'valid.json')=={'retained':'authority'}
print(json.dumps(refused))
'''
                environment = {**os.environ, 'COINTOS_CONFIG': str(operational),
                               'COINTOS_PROJECTS': str(registry), 'COINTOS_STATE': str(directory / 'state')}
                result = subprocess.run([sys.executable, '-c', child, str(directory)],
                                        env=environment, capture_output=True, text=True, timeout=2)
                assert result.returncode == 0, 'bounded authority reader failed: ' + result.stderr[-2000:]
                assert json.loads(result.stdout) == ['symlink', 'dangling', 'fifo', 'nonregular']
                assert target.read_text() == '{"retained":"authority"}'
                assert (directory / 'symlink').is_symlink() and (directory / 'dangling').is_symlink()
            assert state.L == live_before, 'storage validation changed live simulated authority'
        self.fault, self.order = {'admission_namespace'}, ['admission_namespace']
        assert self.admission_trial() == 'unique-admission-and-landed'
        return 'authority-corrected-and-landed'

    def admission_trial(self):
        """Real admission reserves execution identity before publishing task/key ownership."""
        state.L['tasks'].pop(self.integration['id'])
        state.L['agents'].pop('integrator')
        self.integration = None
        queues.add(self.project, 'queued', 'b', 'Implement B', stage='implementation')
        b = tasks.create('item', self.project, 'b', 'Implement B', [4], item='b', record_version=1)
        pending, launches, stopped = [], [], []
        failed_thread = 'admission_thread_failure' in self.fault
        failed_key = 'admission_key_failure' in self.fault

        def launched(agent, task, key):
            self.bind_contract(task)
            # runs.launch pins both its local snapshot and durable task record.
            task.setdefault('base_commit', self.refs['main'])
            state.L['tasks'][task['id']].setdefault('base_commit', task['base_commit'])
            launches.append((agent, task, key))

        class Follower:
            def __init__(self, target, args, daemon):
                self.target, self.args = target, args
            def start(self):
                if failed_thread:
                    raise RuntimeError('thread resource unavailable')
                pending.append((self.target, self.args))

        with tempfile.TemporaryDirectory(prefix='cointos-sim-admission-') as temporary:
            directory = Path(temporary)
            keyfile = directory / 'keys.json'
            keyfile.write_text(json.dumps({'agents': {'worker-a00004': 'recorded-key'}}))
            with patch.dict(keys.OWNERS, {'issued-key': ('worker-a00003', 'background')}, clear=True), \
                 patch.dict(keys.ISSUED, {'worker-a00003': 'issued-key'}, clear=True), \
                 patch.object(keys, 'KEYS', keyfile), \
                 patch.object(opencode, 'run_dir', side_effect=lambda run: directory / run), \
                 patch.object(runs.threading, 'Thread', Follower), \
                 patch.object(runs, 'launch', side_effect=launched), \
                 patch.object(opencode, 'stop', side_effect=lambda run: stopped.append(run)):
                if failed_key:
                    original_registry = keyfile.read_bytes()
                    invalid = ['{', 'null', '[]', '"registry"', '{"agents":null}',
                               '{"agents":[]}', '{"agents":{"worker-old":null}}',
                               '{"agents":{"worker-old":7}}', '{"agents":{"worker-old":[]}}',
                               '{"agents":{"worker-old":""}}', '{"agents":{"":"old-key"}}',
                               '{"coin":null}', '{"coin":false}', '{"coin":7}', '{"coin":""}',
                               '{"coin":"first","coin":"second"}',
                               '{"agents":{"worker-old":"first","worker-old":"second"}}',
                               '{"agents":{"worker-a":"same","worker-b":"same"}}',
                               '{"coin":"same","agents":{"worker-a":"same"}}',
                               '{"agents":{"coin":"reserved"}}']
                    for contents in [*invalid, original_registry.decode()]:
                        permission_fault = contents == original_registry.decode()
                        keyfile.write_text(contents)
                        unchanged = copy.deepcopy((b, state.L['agents'], keys.OWNERS, keys.ISSUED))
                        if permission_fault:
                            keyfile.chmod(0)
                        try:
                            for operation in (keys.recorded, keys.load,
                                              lambda: keys.issue('worker-probe', 'background'),
                                              lambda: runs.start(b)):
                                try:
                                    operation()
                                except (ValueError, OSError):
                                    pass
                                else:
                                    raise AssertionError('invalid or unreadable registry was treated as absent')
                                assert (b, state.L['agents'], keys.OWNERS, keys.ISSUED) == unchanged, \
                                    'registry read failure changed task or gateway ownership'
                        finally:
                            keyfile.chmod(0o600)
                        assert keyfile.read_bytes() == contents.encode(), 'registry failure overwrote prior key bytes'
                        assert not pending and not launches and not stopped
                    keyfile.write_bytes(original_registry)
                    self.key_nonce_scenarios(keyfile)
                    keyfile.write_bytes(original_registry)
                    absent = directory / 'absent-keys.json'
                    with patch.object(keys, 'KEYS', absent):
                        assert keys.stored() == {} and keys.recorded() == {}
                        keys._persist('worker-initial', 'initial-key')
                        assert keys.recorded() == {'worker-initial': 'initial-key'}
                if 'admission_launch_artifacts' in self.fault:
                    target = directory / 'worker-a00009'
                    target.mkdir()
                    original = {'opencode.json': 'prior config', 'run.json': 'prior specification',
                                'server.json': 'prior server', 'exit.json': 'prior exit',
                                'events.jsonl': 'prior events'}
                    for name, text in original.items():
                        (target / name).write_text(text)
                    for existing_config in (True, False):
                        if not existing_config:
                            (target / 'opencode.json').unlink()
                        with patch.object(opencode, 'settings', return_value={}), \
                             patch.object(opencode.subprocess, 'run') as systemd:
                            try:
                                opencode.launch({**state.CONFIG, 'structured_compaction': False},
                                                'worker-a00009', b, 'fixture-key', 'Work', [])
                            except FileExistsError:
                                pass
                            else:
                                raise AssertionError('relaunch reused historical run artifacts')
                            assert not systemd.called, 'relaunch started historical execution identity'
                        assert all((target / name).read_text() == text for name, text in original.items()
                                   if name != 'opencode.json' or existing_config)
                    return 'historical-run-artifacts-preserved'
                if 'admission_namespace' in self.fault:
                    a = self.worker
                    a.update(status='running', agent='worker-a00001', receipt=None, acceptance=None)
                    state.L['agents']['worker-a00001'] = {'id': 'worker-a00001', 'task': a['id']}
                    state.L['exiting']['worker-a00002'] = self.clock
                    historical = directory / 'worker-a00005'
                    historical.mkdir()
                    (historical / 'events.jsonl').write_text('historical evidence')
                    (directory / 'worker-a00006').symlink_to(historical, target_is_directory=True)
                    for alias in ('worker-a00001', 'worker-a00002'):
                        before = copy.deepcopy(b)
                        try:
                            lifecycle.start(b, alias)
                        except ValueError:
                            pass
                        else:
                            raise AssertionError('direct lifecycle admission aliased existing run')
                        assert b == before
                    choices = ['a00001', 'a00002', 'a00003', 'a00004', 'a00005', 'a00006', 'a00007']
                else:
                    choices = ['a00008', 'a00007']
                before = copy.deepcopy((b, state.L['agents'], keys.OWNERS, keys.ISSUED))
                persisted = keys.write_json
                def write(path, value, mode=0o644):
                    assert b['status'] == 'waiting' and len(pending) == 1, \
                        'task ownership changed before follower and durable key admission'
                    assert 'fresh-key' not in keys.OWNERS, 'gateway adopted key before durable publication'
                    if failed_key:
                        raise OSError('key persistence unavailable')
                    persisted(path, value, mode)
                with patch.object(runs.secrets, 'token_hex', side_effect=choices), \
                     patch.object(keys.secrets, 'token_urlsafe', return_value='fresh-key'), \
                     patch.object(keys, 'write_json', side_effect=write):
                    try:
                        run = runs.start(b)
                    except (OSError, RuntimeError):
                        assert failed_key or failed_thread
                        assert (b, state.L['agents'], keys.OWNERS, keys.ISSUED) == before, \
                            'failed admission changed task or gateway ownership'
                        assert keys.recorded() == {'worker-a00004': 'recorded-key'}
                        for target, args in pending:
                            target(*args)
                        assert not launches and not stopped, 'unregistered follower launched or stopped a unit'
                        assert (directory / 'worker-a00008').is_dir(), 'failed admission lost reserved namespace'
                        failed_key = failed_thread = False
                        pending.clear()
                        run = runs.start(b)
                assert run == 'worker-a00007' and len(pending) == 1
                assert keys.recorded()[run] == 'fresh-key' and keys.owner('fresh-key') == (run, 'background')
                if 'admission_namespace' in self.fault:
                    assert state.L['agents']['worker-a00001']['task'] == a['id'] and a['agent'] == 'worker-a00001'
                    assert (historical / 'events.jsonl').read_text() == 'historical evidence'
                self.worker = b
                self.refs[b['branch']] = self.node([self.refs['main']])
                self.worktrees[b['worktree']] = b['branch']
                def complete(run, on_event):
                    api.dispatch('finish', {'caller': {'task': b['id'], 'run': run},
                                            'outcome': 'complete', 'detail': 'useful admitted work'})
                    return {'finish': 'stop', 'code': 0}
                with patch.object(opencode, 'watch', side_effect=complete):
                    for target, args in pending:
                        target(*args)
                assert launches[0][0] == run and launches[0][2] == 'fresh-key'
                assert b['status'] == 'review' and stopped == [run]
                self.integration = integration = spawner.integrations()[0][1]()
                self.start(integration, 'integrator-admitted')
                self.candidate = self.node([self.refs['main'], b['receipt']['evidence']['commit']])
                self.refs[integration['branch']] = self.candidate
                landing.land(integration['id'], self.candidate, 'integrator-admitted')
                self.invariants()
                return 'unique-admission-and-landed'

    def key_nonce_scenarios(self, keyfile):
        """Actual registry allocation, adoption and persistence share one key namespace."""
        data = {'coin': 'coin-key', 'agents': {'worker-a00004': 'recorded-key'}}
        keyfile.write_text(json.dumps(data))
        with patch.dict(keys.OWNERS, {'coin-key': ('coin', 'coin'),
                                     'issued-key': ('worker-a00003', 'background')}, clear=True), \
             patch.dict(keys.ISSUED, {'worker-a00003': 'issued-key'}, clear=True), \
             patch.object(keys, 'ENDED', {'ended-key'}):
            with patch.object(keys.secrets, 'token_urlsafe', side_effect=[
                    'coin-key', 'recorded-key', 'issued-key', 'ended-key', 'nonce-key']):
                allocated = keys.issue('worker-nonce', 'background')
            assert allocated == 'nonce-key', 'key allocation reused Coin/live/persisted/ended identity'
            assert keys.recorded()['worker-nonce'] == allocated and keys.ended('ended-key')
            assert keys.owner('coin-key') == ('coin', 'coin')
            assert keys.owner('issued-key') == ('worker-a00003', 'background')
            before = copy.deepcopy((keys.OWNERS, keys.ISSUED, keys.ENDED))
            persisted = keyfile.read_bytes()
            keys.adopt('worker-nonce', 'background', allocated)
            assert (keys.OWNERS, keys.ISSUED, keys.ENDED) == before, 'exact adoption replay changed identity'
            conflicts = [('coin', 'background', 'other-key'), ('worker-other', 'background', 'coin-key'),
                         ('worker-nonce', 'coin', allocated), ('worker-nonce', 'background', 'other-key'),
                         ('worker-other', 'background', 'ended-key'),
                         ('worker-other', 'background', 'issued-key')]
            operations = [lambda actor=actor, klass=klass, key=key: keys.adopt(actor, klass, key)
                          for actor, klass, key in conflicts]
            operations += [lambda actor=actor: keys.issue(actor, 'background')
                           for actor in ('coin', 'worker-nonce', 'worker-a00003', 'worker-a00004')]
            operations += [lambda actor=actor, key=key: keys._persist(actor, key)
                           for actor, key in [('worker-nonce', 'changed-key'), ('worker-other', 'coin-key'),
                                              ('worker-other', allocated), ('coin', 'other-key')]]
            for operation in operations:
                try:
                    operation()
                except ValueError:
                    pass
                else:
                    raise AssertionError('conflicting gateway identity was accepted')
                assert (keys.OWNERS, keys.ISSUED, keys.ENDED) == before
                assert keyfile.read_bytes() == persisted, 'identity conflict overwrote persisted ownership'
            def concurrent_registry_change(size):
                changed = json.loads(persisted)
                changed['agents']['worker-raced'] = 'concurrent-key'
                keyfile.write_text(json.dumps(changed))
                return 'proposed-key'
            with patch.object(keys.secrets, 'token_urlsafe', side_effect=concurrent_registry_change):
                try:
                    keys.issue('worker-raced', 'background')
                except ValueError:
                    pass
                else:
                    raise AssertionError('key publication overwrote concurrently assigned actor')
            assert keys.recorded()['worker-raced'] == 'concurrent-key'
            assert (keys.OWNERS, keys.ISSUED, keys.ENDED) == before
            keyfile.write_text(json.dumps({'agents': data['agents']}))
            retained = keyfile.read_bytes()
            try:
                keys.load()
            except ValueError:
                pass
            else:
                raise AssertionError('existing keyless registry silently bootstrapped Coin')
            assert keyfile.read_bytes() == retained, 'missing Coin erased known gateway ownership'
            keyfile.unlink()
            with patch.object(keys.secrets, 'token_urlsafe', side_effect=[
                    'issued-key', 'ended-key', 'coin-key', 'new-coin-key']):
                keys.load()
            assert keys.stored()['coin'] == 'new-coin-key', 'Coin allocation aliased known live/ended gateway ownership'
            assert keys.owner('new-coin-key') == ('coin', 'coin')

    def hidden_trial(self):
        """A writer's red receipt cannot authorize its hidden dependency before review."""
        w, integration = self.worker, self.integration
        queues.add(self.project, 'queued', 'b', 'Depends on: a\nImplement the tested contract', stage='implementation')

        def readiness():
            records = [r for r in queues.records().values() if r['project'] == 'sim']
            return queues.readiness(records, {r['item'] for r in records if r.get('done')})['b']

        assert w['status'] == 'review' and not w.get('acceptance'), 'red writer bypassed independent review'
        assert readiness() != 'ready', 'unreviewed red writer unlocked its implementation'
        parent = self.refs['main']
        if 'hidden_validation_races' in self.fault:
            faults = ('test_timeout', 'mutating_tests', 'missing_packet', 'tampered_packet',
                      'main_moved', 'candidate_moved', 'worker_moved_during_test',
                      'receipt_changed_during_test', 'hold_integrator', 'hold_during_test',
                      'kill_during_test', 'cancel_during_test', 'production_changed')
            seed = int(self.clock - 1000)
            for index, fault in enumerate(faults):
                self.reset('hidden_validation_races', seed + index)
                self.fault.add(fault)
                self.order.append(fault)
                with patch.object(contracts, 'production', return_value=['app.py'] if fault == 'production_changed' else []):
                    try:
                        landing.land(self.integration['id'], self.candidate, 'integrator')
                    except ValueError:
                        pass
                    else:
                        raise AssertionError('invalid hidden review gained authority: ' + fault)
                assert not self.worker.get('acceptance') and not queues.records().get(self.worker['record'], {}).get('done')
                assert 'advance-main' not in self.trace and not self.integration.get('landing')
            return 'hidden-invalid-review-refused'
        if 'hidden_blocked_review' in self.fault:
            lifecycle.submit(integration['id'], 'integrator', 'blocked', 'contract assumptions unsupported')
            assert w['status'] == 'failed' and readiness() != 'ready'
            scanned = {'sim': queues.live('sim')}
            ready = {'sim': queues.readiness(scanned['sim'], set())}
            spawner.repair_work(scanned)
            controller = tasks.request_repair(w)[0]
            assert controller and controller['role'] == 'operator', 'blocked contract lacked recovery ownership'
            return 'hidden-blocked-review-to-controller'
        if 'hidden_rejected_review' in self.fault:
            lifecycle.returned(integration, 'integrator', 'repair contract ownership and assertion')
            assert w['status'] == 'waiting' and not w['receipt'] and readiness() != 'ready'
            self.start(w, 'writer-revised')
            with patch.object(contracts, 'contracts', return_value=[]):
                lifecycle.submit(w['id'], 'writer-revised', 'complete', 'corrected contract',
                                 {'commit': self.refs[w['branch']], 'passing': False, 'packet_tests': 1})
            self.integration = integration = spawner.integrations()[0][1]()
            self.start(integration, 'reviewer-revised')
            self.candidate = self.node([parent, self.refs[w['branch']]])
            self.refs[integration['branch']] = self.candidate
        run = integration['agent']
        if 'hidden_save_replacement' in self.fault:
            seed = int(self.clock - 1000)
            for index, mode in enumerate(('before', 'after', 'retry')):
                self.reset('hidden_save_replacement', seed + index)
                w, integration = self.worker, self.integration
                durable = copy.deepcopy(state.L)
                def persist():
                    nonlocal durable
                    if mode == 'after':
                        durable = copy.deepcopy(state.L)
                    raise Crash()
                with patch.object(contracts, 'production', return_value=[]), patch.object(landing, 'save', side_effect=persist):
                    try:
                        landing.land(integration['id'], self.candidate, 'integrator')
                    except Crash:
                        pass
                assert self.refs['main'] == parent and 'advance-main' not in self.trace
                if mode == 'retry':
                    def flush_retry():
                        nonlocal durable
                        durable = copy.deepcopy(state.L)
                    with patch.object(landing, 'save', side_effect=flush_retry):
                        assert landing.land(integration['id'], self.candidate, 'integrator')['ok']
                    assert durable['tasks'][w['id']].get('acceptance'), \
                        'matching completion retry acknowledged undurable hidden acceptance'
                state.L.clear()
                state.L.update(state.fresh(durable))
                w = self.worker = state.L['tasks'][w['id']]
                integration = self.integration = state.L['tasks'][integration['id']]
                if mode == 'before':
                    state.L['agents'].clear()
                    lifecycle.orphaned(integration)
                    self.start(integration, 'reviewer-replaced')
                with patch.object(contracts, 'production', return_value=[]):
                    landing.land(integration['id'], self.candidate, integration['agent'])
                assert w['acceptance']['via'] == 'tests' and self.refs['main'] == parent
                self.invariants()
            return 'hidden-save-replacement-recovered'
        with patch.object(contracts, 'production', return_value=[]):
            landing.land(integration['id'], self.candidate, run)
        acceptance = copy.deepcopy(w['acceptance'])
        if 'hidden_green_review' in self.fault:
            assert acceptance['via'] == 'landing' and self.refs['main'] == self.candidate
            assert readiness() == 'ready'
            assert landing.land(integration['id'], self.candidate, 'retired-run')['ok']
            self.invariants()
            return 'green-contract-reviewed-and-published'
        assert acceptance == {'commit': self.candidate, 'worker_commit': w['receipt']['evidence']['commit'],
                              'via': 'tests', 'stage': 'test-contract',
                              'gate': {'suite': 1, 'failed': 1, 'red_on_main': int('hidden_red_main' in self.fault)}}, 'reviewed red candidate was not accepted as hidden tests'
        assert self.refs['main'] == parent and 'advance-main' not in self.trace and not integration.get('landing')
        assert readiness() == 'ready', 'reviewed hidden contract did not unlock implementation'
        child = tasks.create('item', self.project, 'b', 'Implement the tested contract', [4], item='b', record_version=1)
        assert landing.tests_of(child) == [self.candidate], 'dependent received unreviewed writer tree'
        assert landing.land(integration['id'], self.candidate, 'retired-run')['ok']
        assert w['acceptance'] == acceptance
        self.invariants()
        return 'hidden-reviewed-without-publication'

    def producer_failure_trial(self):
        """Failed metadata writes still run explicit server-group cleanup."""
        before = copy.deepcopy(state.L['tasks'])
        original_writer = opencode.write_json
        original_text = Path.write_text
        for failed_name in ('server.json', 'exit.json'):
            cleaned, attempted = [], []
            with tempfile.TemporaryDirectory(prefix='cointos-sim-producer-failure-') as temporary:
                directory = Path(temporary)
                (directory / 'run.json').write_text(json.dumps({
                    'task': {'id': self.worker['id'], 'worktree': self.worker['worktree']},
                    'command': ['opencode', 'run'], 'session': None, 'text': 'Work'}))

                def write(path, value):
                    attempted.append((path.name, value))
                    if path.name == failed_name:
                        raise OSError('metadata storage unavailable')
                    original_writer(path, value)

                def direct_write(path, text, *args, **kwargs):
                    if path.parent == directory and path.name in ('server.json', 'exit.json'):
                        attempted.append((path.name, json.loads(text)))
                        if path.name == failed_name:
                            raise OSError('metadata storage unavailable')
                    return original_text(path, text, *args, **kwargs)

                client = SimpleNamespace(stdin=io.BytesIO(), wait=lambda: 0)
                with patch.object(opencode, 'start_server', return_value=(SimpleNamespace(pid=401), 'http://sim')), \
                     patch.object(opencode.subprocess, 'Popen', return_value=client), \
                     patch.object(opencode, 'stop_group', side_effect=lambda pid: cleaned.append(pid)), \
                     patch.object(opencode, 'write_json', side_effect=write), \
                     patch.object(Path, 'write_text', new=direct_write):
                    try:
                        opencode.serve_run(directory)
                    except OSError:
                        pass
                    else:
                        raise AssertionError('producer hid metadata write failure')
                assert cleaned == [401], 'metadata write failure skipped explicit server cleanup: ' + failed_name
                assert attempted[-1] == ('exit.json', {'code': 1 if failed_name == 'server.json' else 0})
        assert state.L['tasks'] == before, 'producer execution facts changed task settlement'
        return 'producer-error-cleaned'

    def artifact_trial(self):
        """Interleave the real unit producer and follower before metadata publication."""
        w = self.worker
        state.L['tasks'].pop(self.integration['id'])
        state.L['agents'].pop('integrator')
        self.integration = None
        w.update(status='running', agent='worker', receipt=None, acceptance=None,
                 session='session-worker')
        state.L['agents']['worker'] = {'id': 'worker', 'task': w['id'], 'class': 'background',
                                       'engaged': True, 'thoughts': 1, 'started_at': self.clock,
                                       'last_activity': self.clock, 'session': 'session-worker'}
        artifacts = (w['branch'], w['worktree'], self.refs[w['branch']])
        stopped, inspected = [], []
        interrupted = next((f.rsplit('_', 1)[1] + '.json' for f in self.fault
                            if f.startswith('artifact_interrupted_')), None)
        original_write, original_replace = Path.write_text, opencode.os.replace
        expected = {'server.json': {'pid': 401, 'url': 'http://sim'}, 'exit.json': {'code': 0}}
        if interrupted == 'server.json':
            expected['exit.json']['code'] = 1
        old_server = {'pid': 399, 'url': 'http://previous'}

        def suspend(seconds):
            raise ObservationYield()

        with tempfile.TemporaryDirectory(prefix='cointos-sim-publication-') as temporary:
            directory = Path(temporary)
            (directory / 'run.json').write_text(json.dumps({
                'task': {'id': w['id'], 'worktree': w['worktree']},
                'command': ['opencode', 'run'], 'session': None, 'text': 'Work'}))
            if interrupted == 'server.json':
                (directory / 'server.json').write_text(json.dumps(old_server))

            def inspect(target):
                inspected.append(target.name)
                if target.name == 'server.json' and interrupted != 'exit.json':
                    try:
                        runs.follow('worker', None, None)
                    except ObservationYield:
                        pass
                    assert 'worker' in state.L['agents'] and not stopped, \
                        'server publication exposed partial metadata and stopped live assignment'
                    assert w['status'] == 'running' and not w['receipt']
                elif target.name == 'exit.json' and target.exists():
                    assert json.loads(target.read_text()) == expected[target.name], \
                        'exit publication exposed incomplete metadata'
                assert (w['branch'], w['worktree'], self.refs[w['branch']]) == artifacts
                assert w['session'] == 'session-worker'

            def direct_write(target, text, *args, **kwargs):
                if target.parent == directory and target.name in expected:
                    original_write(target, text[:len(text) // 2], *args, **kwargs)
                    inspect(target)
                    if target.name == interrupted:
                        raise Crash()
                return original_write(target, text, *args, **kwargs)

            def replace(source, target):
                target = Path(target)
                if target.parent == directory and target.name in expected:
                    assert json.loads(Path(source).read_text()) == expected[target.name]
                    inspect(target)
                    if target.name == interrupted:
                        raise Crash()
                return original_replace(source, target)

            client = SimpleNamespace(stdin=io.BytesIO(), wait=lambda: 0)
            with patch.object(opencode, 'run_dir', return_value=directory), \
                 patch.object(opencode, 'start_server', return_value=(SimpleNamespace(pid=401), 'http://sim')), \
                 patch.object(opencode.subprocess, 'Popen', return_value=client), \
                 patch.object(opencode, 'stop_group'), \
                 patch.object(opencode, 'stop', side_effect=lambda run: stopped.append(run)), \
                 patch.object(opencode, 'active', return_value=True), \
                 patch.object(opencode.time, 'sleep', side_effect=suspend):
                with patch.object(Path, 'write_text', new=direct_write), \
                     patch.object(opencode.os, 'replace', side_effect=replace):
                    try:
                        opencode.serve_run(directory)
                    except Crash:
                        assert interrupted, 'unexpected producer interruption'
                assert inspected, 'production producer did not cross publication boundary'
                if interrupted:
                    target = directory / interrupted
                    assert (json.loads(target.read_text()) == old_server if target.exists()
                            else interrupted == 'exit.json'), 'interrupted publication changed visible metadata'
                    private = list(directory.glob('.' + interrupted + '.*.tmp'))
                    assert len(private) == 1, 'interrupted producer exposed or lost private publication'
                    assert json.loads(private[0].read_text()) == expected[interrupted]
                    assert 'worker' in state.L['agents'] and not stopped
                    expected['exit.json']['code'] = 0
                    client.stdin = io.BytesIO()
                    opencode.serve_run(directory)
                assert {name: json.loads((directory / name).read_text()) for name in expected} == expected
                with patch.object(opencode, 'active', return_value=False):
                    runs.follow('worker', None, None)
        assert stopped == ['worker'] and 'worker' not in state.L['agents']
        assert w['status'] == 'waiting' and not w['receipt'] and not w['acceptance']
        return 'atomic-run-artifacts-observed'

    def observer_trial(self):
        """Actual follower waits through unavailable unit observations, then reconciles facts."""
        w = self.worker
        state.L['tasks'].pop(self.integration['id'])
        state.L['agents'].pop('integrator')
        self.integration = None
        w.update(status='running', agent='worker', receipt=None, acceptance=None,
                 session='session-worker')
        state.L['agents']['worker'] = {'id': 'worker', 'task': w['id'], 'class': 'background',
                                       'engaged': True, 'thoughts': 1, 'started_at': self.clock,
                                       'last_activity': self.clock, 'session': 'session-worker'}
        artifacts = (w['branch'], w['worktree'], self.refs[w['branch']])
        phase, stopped, facts_seen, observations = 0, [], [], []
        receipted = 'observer_query_oserror' in self.fault
        terminal_tail = 'observer_terminal_tail' in self.fault
        malformed = 'observer_malformed_shapes' in self.fault
        error = {'name': 'ProviderError', 'data': {'message': 'upstream unavailable'}}
        original_ended = lifecycle.ended

        def query(*args, **kwargs):
            observations.append(phase)
            if phase == 0:
                if terminal_tail:
                    return subprocess.CompletedProcess(args, 0, 'active', '')
                if receipted:
                    raise OSError('temporary unit query failure')
                stdout = 'failed' if 'observer_structured_error' in self.fault else ''
                return subprocess.CompletedProcess(args, 1, stdout, 'Failed to connect to bus')
            return subprocess.CompletedProcess(args, 0 if phase == 1 else 3,
                                               'active' if phase == 1 else 'inactive', '')

        def ended(run, facts):
            facts_seen.append(copy.deepcopy(facts))
            original_ended(run, facts)

        with tempfile.TemporaryDirectory(prefix='cointos-sim-observer-') as temporary:
            directory = Path(temporary)
            (directory / 'server.json').write_text(json.dumps({'pid': 401, 'url': 'http://sim'}))
            if terminal_tail:
                (directory / 'events.jsonl').write_text(json.dumps(
                    {'type': 'error', 'sessionID': 'session-final', 'error': error}))
            elif malformed:
                shapes = [None, [], 4, 'event', {'part': ['invalid']}, {'part': True},
                          {'sessionID': ['invalid']}, {'part': {'type': 'text', 'text': 7}},
                          {'part': {'type': 'tool', 'state': 'invalid'}},
                          {'part': {'type': 'tool', 'state': {'input': ['invalid']}}},
                          {'part': {'type': 'text', 'text': 'useful recovery detail'}},
                          {'part': {'type': 'tool', 'tool': 'check',
                                    'state': {'status': 'completed', 'input': {'command': 'check'},
                                              'output': 'verified result'}}},
                          {'sessionID': 'session-worker',
                           'part': {'type': 'text', 'text': 'later valid session'}}]
                (directory / 'events.jsonl').write_text(''.join(json.dumps(event) + '\n' for event in shapes))
                with patch.object(opencode, 'run_dir', return_value=directory):
                    evidence = opencode.evidence('worker', 20)
                assert any('useful recovery detail' in line for line in evidence)
                assert any('verified result' in line for line in evidence)

            def tick(seconds):
                nonlocal phase
                assert phase < 4, 'unit observer did not finish after confirmed terminal state'
                assert 'worker' in state.L['agents'], 'ambiguous query released live unit'
                assert not stopped and not w['acceptance'], 'observation stopped or accepted live work'
                assert (w['branch'], w['worktree'], self.refs[w['branch']]) == artifacts
                expected_session = 'session-final' if terminal_tail and phase == 2 else 'session-worker'
                assert w['session'] == expected_session, 'observer consumed live tail or lost terminal session'
                assert w['status'] == ('review' if w['receipt'] else 'running')
                if malformed and phase == 0:
                    assert state.L['agents']['worker']['doing'] == 'later valid session'
                phase += 1
                if phase == 1 and not terminal_tail:
                    with (directory / 'events.jsonl').open('a') as stream:
                        stream.write(json.dumps({'sessionID': 'session-worker',
                                                 'part': {'type': 'text', 'text': 'working'}}) + '\n')
                elif phase == 2:
                    if receipted:
                        api.dispatch('finish', {'caller': {'task': w['id'], 'run': 'worker'},
                                                'outcome': 'complete', 'detail': 'checked result'})
                    if not terminal_tail:
                        events = [{'type': 'step_finish', 'part': {'reason': 'stop'}}]
                        if 'observer_structured_error' in self.fault:
                            events.append({'type': 'error', 'error': error})
                        with (directory / 'events.jsonl').open('a') as stream:
                            stream.write(''.join(json.dumps(event) + '\n' for event in events))
                    (directory / 'exit.json').write_text(json.dumps({'code': 0}))

            with patch.object(opencode, 'run_dir', return_value=directory), \
                 patch.object(opencode.subprocess, 'run', side_effect=query), \
                 patch.object(opencode.time, 'sleep', side_effect=tick), \
                 patch.object(opencode, 'stop', side_effect=lambda run: stopped.append((run, phase))), \
                 patch.object(lifecycle, 'ended', side_effect=ended):
                runs.follow('worker', None, None)
            if terminal_tail:
                (directory / 'events.jsonl').write_text('{"type":"error","sessionID":"unfinished')
                emitted = []
                with patch.object(opencode, 'run_dir', return_value=directory), \
                     patch.object(opencode, 'active', return_value=False), \
                     patch.object(opencode.time, 'sleep', return_value=None):
                    truncated = opencode.watch('worker', lambda kind, value: emitted.append((kind, value)))
                assert truncated == {'finish': None, 'code': 0}, 'truncated terminal tail fabricated execution facts'
                assert not any(kind == 'session' for kind, value in emitted), 'truncated tail fabricated session'
        assert phase == 3 and observations == [0, 1, 2, 3], (
            'terminal observer discarded valid final event' if terminal_tail
            else 'malformed event ended observation before later valid session' if malformed
            else 'unit query ambiguity ended observation before recovery')
        assert stopped == [('worker', 3)] and 'worker' not in state.L['agents']
        assert facts_seen[0]['code'] == 0 and facts_seen[0]['finish'] == (None if terminal_tail else 'stop')
        assert (w['branch'], w['worktree'], self.refs[w['branch']]) == artifacts
        assert not w['acceptance'], 'terminal execution facts fabricated acceptance'
        if 'observer_structured_error' in self.fault or terminal_tail:
            assert facts_seen[0]['error'] == error, 'observer lost structured final error'
            assert 'upstream unavailable' in w['note'], 'unreceipted retry lost error diagnosis'
        if not receipted:
            assert w['status'] == 'waiting' and not w['receipt'], 'exit code replaced completion receipt'
            return 'observed-terminal-without-receipt'
        assert w['status'] == 'review' and w['receipt']['run'] == 'worker'
        self.integration = integration = spawner.integrations()[0][1]()
        self.start(integration, 'integrator-observed')
        candidate = self.node([self.refs['main'], w['receipt']['evidence']['commit']])
        self.refs[integration['branch']] = candidate
        landing.land(integration['id'], candidate, 'integrator-observed')
        self.invariants()
        return 'observed-receipt-and-landed'

    def receipt_trial(self):
        """Daemon loss around worker receipt persistence, then native finish replay."""
        w, integration = self.worker, self.integration
        state.L['tasks'].pop(integration['id'])
        state.L['agents'].pop('integrator')
        w.update(status='running', agent='worker', receipt=None, acceptance=None)
        state.L['agents']['worker'] = {'id': 'worker', 'task': w['id'], 'last_activity': self.clock}
        self.durable = copy.deepcopy(state.L)
        body = {'caller': {'task': w['id'], 'run': 'worker'}, 'outcome': 'complete', 'detail': 'result'}
        try:
            api.dispatch('finish', body)
        except Crash:
            state.L.clear()
            state.L.update(copy.deepcopy(self.durable))
            self.trace.append('reload-worker-receipt')
        self.fault, self.order = set(), []
        receipt = api.dispatch('finish', body)['receipt']
        assert api.dispatch('finish', body)['receipt'] == receipt, 'receipt replay changed durable authority'
        self.worker = w = state.L['tasks'][w['id']]
        assert w['status'] == 'review' and receipt['evidence']['commit'] == self.refs[w['branch']]
        state.L['agents'].pop('worker')
        options = spawner.integrations()
        assert len(options) == 1, 'receipt recovery stranded review'
        self.integration = integration = options[0][1]()
        self.start(integration, 'integrator-recovered')
        self.candidate = self.node([self.refs['main'], receipt['evidence']['commit']])
        self.refs[integration['branch']] = self.candidate
        landing.land(integration['id'], self.candidate, 'integrator-recovered')
        self.invariants()
        return 'receipt-recovered-and-landed'

    def adoption_trial(self):
        """Replace the daemon while its managed units or receipts survive it."""
        if 'adopt_published_exhausted' in self.fault:
            return self.published_adoption_trial()
        w, integration = self.worker, self.integration
        worker_case = self.fault.intersection(('adopt_live_worker', 'adopt_missing_key',
                                              'adopt_receipted_worker'))
        if worker_case:
            state.L['tasks'].pop(integration['id'])
            state.L['agents'].pop('integrator')
            if 'adopt_receipted_worker' not in self.fault:
                w.update(status='running', agent='worker', receipt=None, acceptance=None)
            state.L['agents']['worker'] = {'id': 'worker', 'task': w['id'], 'class': 'background',
                                           'session': 'session-worker', 'pid': 401,
                                           'engaged': True, 'thoughts': 1, 'started_at': self.clock,
                                           'last_activity': self.clock}
            target, original_run = w, 'worker'
        else:
            target, original_run = integration, 'integrator'
            state.L['agents'][original_run].update(session='session-integrator', pid=402)
            # This marker belongs to the dead daemon's validation, not the live
            # integrator unit; retaining it would refuse the resumed request.
            integration['validating'] = True
        target['session'] = 'session-' + original_run
        before_runs, before_commit = target['runs'], self.refs[target['branch']]
        previous = copy.deepcopy(state.L)
        state.L.clear()
        state.L.update(state.fresh(previous))
        self.worker = w = state.L['tasks'][w['id']]
        target = state.L['tasks'][target['id']]
        self.integration = None if worker_case else target
        assert not target.get('validating'), 'daemon-local validation survived replacement'
        recorded = {} if 'adopt_missing_key' in self.fault else {original_run: 'gateway-key'}
        active = 'adopt_dead_integrator' not in self.fault
        stopped, adopted = [], []
        with patch.object(runs.keys, 'recorded', return_value=recorded), \
             patch.object(runs.keys, 'adopt', side_effect=lambda *args: adopted.append(args)), \
             patch.object(runs.opencode, 'active', return_value=active), \
             patch.object(runs.opencode, 'find_processes', return_value={original_run: [401]}), \
             patch.object(runs.opencode, 'stop_group', side_effect=lambda pid, **kw: stopped.append(pid)):
            runs.adopt(previous)
        receipted = 'adopt_receipted_worker' in self.fault
        survived = active and bool(recorded)
        assert bool(adopted) == survived, 'adopted a run without exact task/run or receipt/key/unit ownership'
        assert bool(stopped) != survived, 'orphan process was retained or owned process stopped'
        assert target['runs'] == before_runs, 'replacement charged a new run before admission'
        assert target['session'] == 'session-' + original_run, 'replacement discarded session'
        assert self.refs[target['branch']] == before_commit, 'replacement discarded committed work'
        if receipted:
            receipt = copy.deepcopy(w['receipt'])
            recovery.enforce()
            assert original_run in state.L['agents'], 'replacement discarded receipted live reply delivery'
            assert w['status'] == 'review' and w['receipt'] == receipt and not w.get('acceptance')
        admitted = []
        def admit(task):
            run = 'readmitted-' + task['id']
            admitted.append(task['id'])
            self.start(task, run)
            return run
        state.L['paused'] = False
        state.L['models'][state.CONFIG['work_model']]['up'] = True
        state.L['memory']['headroom_gb'] = state.CONFIG['memory']['agent_memory_gb'] * 4
        with patch.object(spawner.runs, 'start', side_effect=admit):
            api.dispatch('prepare-restart', {})
            spawner.spawn()
            assert not admitted, 'replacement drain admitted new work'
            api.dispatch('cancel-restart', {})
            spawner.spawn()
            first = list(admitted)
            spawner.spawn()
        assert admitted == first, 'replacement admitted duplicate task runs'
        assert len(admitted) == (1 if receipted or not survived else 0), 'replacement stranded ready work'
        if receipted:
            assert w['id'] not in admitted and w['runs'] == before_runs, 'receipt was reopened as worker admission'
        if worker_case:
            if w['status'] == 'running':
                lifecycle.submit(w['id'], w['agent'], 'complete', 'result',
                                 {'commit': self.refs[w['branch']], 'tests': landing.tests_of(w), 'packet_tests': 1})
                state.L['agents'].clear()
                options = spawner.integrations()
                assert len(options) == 1, 'adopted worker receipt stranded review'
                self.integration = options[0][1]()
                self.start(self.integration, 'integration-after-adoption')
            else:
                self.integration = next(t for t in state.L['tasks'].values() if t['kind'] == 'integrate')
        self.candidate = self.node([self.refs['main'], w['receipt']['evidence']['commit']])
        self.refs[self.integration['branch']] = self.candidate
        landing.land(self.integration['id'], self.candidate, self.integration['agent'])
        self.invariants()
        assert w.get('acceptance'), 'replacement never drained reviewed work'
        if receipted:
            settled = copy.deepcopy(w)
            stopped_units = []
            with patch.object(opencode, 'watch', return_value={'finish': 'stop', 'code': 0}), \
                 patch.object(opencode, 'stop', side_effect=lambda run: stopped_units.append(run)):
                runs.follow(original_run, None, None)
            assert stopped_units == [original_run] and original_run not in state.L['agents']
            assert w == settled, 'native terminal report reopened receipted/accepted work'
        return 'adopted-and-landed' if survived else 'readmitted-and-landed'

    def published_adoption_trial(self):
        """Production startup must settle published intents before budget enforcement."""
        w, integration = self.worker, self.integration
        integration['fresh_retries'] = state.CONFIG['recovery']['fresh_retries']
        state.L['agents']['integrator']['generation_tokens'] = integration['budget']['generation_tokens']
        self.fault.add('crash_after_ref')
        try:
            landing.land(integration['id'], self.candidate, 'integrator')
        except Crash:
            pass
        else:
            raise AssertionError('publication crash boundary did not execute')
        previous = copy.deepcopy(self.durable)
        assert self.refs['main'] == self.candidate and previous['tasks'][integration['id']]['landing']
        state.L.clear()
        state.ACTIVE['landings'] = 0
        self.fault, self.order = set(), []
        stopped = []
        self.keyfile.write_text(json.dumps({'coin': 'sim-coin', 'agents': {'integrator': 'gateway-key'}}))
        with patch.object(subprocess, 'run', side_effect=lambda command, **kwargs: self.native_startup(command, {'integrator': 402})), \
             patch.object(runs.opencode, 'active', return_value=True), \
             patch.object(runs.opencode, 'find_processes', return_value={'integrator': [402]}), \
             patch.object(runs.opencode, 'stop_group', side_effect=lambda pid, **kw: stopped.append(pid)), \
             patch.object(daemon.snapshots, 'recover_transfers'), \
             patch.object(daemon.snapshots, 'forget_orphans'), \
             patch.object(daemon.snapshots, 'forget_untracked'), \
             patch.object(recovery, 'packet', return_value='terminal evidence'):
            daemon.restore(previous)
            recovery.enforce()
            lifecycle.recover_landings()
        self.worker = state.L['tasks'][w['id']]
        self.integration = state.L['tasks'][integration['id']]
        assert self.worker['status'] == 'done', 'budget enforcement destroyed published intent before recovery'
        assert self.integration['status'] == 'done' and stopped == [], 'published receipt was treated as orphan process'
        assert self.integration['receipt']['run'] == 'integrator'
        assert 'integrator' not in state.L['agents'], 'exhausted reply delivery retained budget ownership'
        assert self.integration['fresh_retries'] == state.CONFIG['recovery']['fresh_retries']
        self.invariants()
        return 'published-intent-before-budget'

    def incorporation_trial(self):
        w, integration = self.worker, self.integration
        submitted = w['receipt']['evidence']['commit']
        self.refs['main'] = self.candidate
        def change(*args):
            if 'incorporate_cancel' in self.fault:
                lifecycle.cancel_task(integration, 'user', 'withdraw review')
            elif 'incorporate_hold' in self.fault:
                lifecycle.hold(w['record'], 'user')
            else:
                w['receipt']['summary'] = 'different submitted work'
        with patch.object(contracts, 'incorporated', side_effect=change):
            try:
                landing.incorporate(w['id'], self.candidate, submitted, 'integrator')
            except ValueError:
                pass
            else:
                raise AssertionError('revoked incorporation validation accepted work')
        assert not w.get('acceptance') and w['status'] == 'review'
        return 'refused-incorporation-race'

    def repair_trial(self):
        """Broad fallback owns a failed episode once and must hand useful work back."""
        if self.fault.intersection(('repair_superseded_periodic', 'repair_live_superseded',
                                    'repair_newer_failed', 'repair_newer_pending')):
            return self.superseded_repair_trial()
        if self.fault.intersection(('repair_prerequisite_arrived', 'repair_obstruction_cleared',
                                    'repair_pending_graph_regression', 'repair_human_cancelled')):
            return self.dependency_arrival_trial()
        state.L['paused'] = False
        w = self.worker
        queue_only = self.fault.intersection(('repair_unknown_dependency', 'repair_dependency_cycle'))
        if queue_only:
            state.L['tasks'].pop(w['id'])
            source = queues.records()[w['record']]
            source['depends'] = ['a' if 'repair_dependency_cycle' in self.fault else 'absent']
        else:
            source = w
            if 'repair_manager_exhausted' in self.fault:
                w.update(status='waiting', receipt=None, agent=None)
                self.start(w, 'worker-exhausted')
                state.L['agents']['worker-exhausted']['generation_tokens'] = w['budget']['generation_tokens']
                with patch.object(recovery, 'packet', return_value='verified terminal recovery evidence'):
                    recovery.enforce()
                assert w['status'] == 'failed', 'exhausted worker did not terminate'
        if 'repair_explicit_hold' in self.fault:
            lifecycle.hold(w['record'], 'user')
            spawner.refresh()
            assert not any(t.get('repair_origin') for t in state.L['tasks'].values()), 'repair ignored user hold'
            lifecycle.unhold(w['record'], 'user')
        spawner.refresh()
        repairs = [t for t in state.L['tasks'].values() if t.get('repair_origin')]
        assert len(repairs) == 1, 'failure did not create exactly one broad repair'
        repair = repairs[0]
        assert repair['budget'] == tasks.schema.budget(state.CONFIG, role='operator'), 'repair inherited exhausted source budget'
        assert set(repair['abilities']) == set(tasks.schema.ABILITIES), 'repair lacks independent broad abilities'
        # Keep the real retirement/obsolescence pass in this coverage: ordinary
        # pending records must survive it without exceptions or lost ownership.
        with patch.object(lifecycle, 'retire', return_value=False), \
             patch.object(lifecycle.snapshots, 'forget_orphans'):
            self.reconcile()
        assert repair['status'] == 'waiting', 'current failure lost its pending repair'
        # Durable replay must reuse the unchanged episode, including terminal repairs.
        durable = copy.deepcopy(state.L)
        state.L.clear()
        state.L.update(state.fresh(durable))
        source = queues.records()[w['record']] if queue_only else state.L['tasks'][source['id']]
        repair = state.L['tasks'][repair['id']]
        for _ in range(3):
            spawner.refresh()
            assert tasks.request_repair(source) == (repair, False), 'restart duplicated broad repair'
        if 'repair_explicit_hold' in self.fault:
            lifecycle.hold(w['record'], 'user')
            assert not spawner.runnable(repair, {}), 'already-created repair ignored user hold'
            lifecycle.unhold(w['record'], 'user')
        try:
            lifecycle.repair_evidence(repair)
        except ValueError:
            pass
        else:
            raise AssertionError('unchanged failure accepted a prose-only repair')
        if 'repair_stale_before_admission' in self.fault:
            lifecycle.revise(w['record'], 'user', 'assignment progressed', 'Implement clarified A')
            with patch.object(lifecycle, 'retire', return_value=False), \
                 patch.object(lifecycle.snapshots, 'forget_orphans'):
                self.reconcile()
            assert repair.get('cancelled') and repair['status'] == 'failed', 'obsolete unadmitted repair survived'
            assert not spawner.runnable(repair, {}), 'obsolete repair admitted against a changed version'
            return 'obsolete-repair-withdrawn'
        assert spawner.next_task() is repair, 'repair starved behind ordinary waiting work'
        self.start(repair, 'repair')
        if 'repair_no_recursive_operator' in self.fault:
            lifecycle.submit(repair['id'], 'repair', 'blocked', 'semantic decision remains unresolved')
            state.L['agents'].pop('repair')
            durable = copy.deepcopy(state.L)
            state.L.clear()
            state.L.update(state.fresh(durable))
            for _ in range(3):
                spawner.refresh()
            assert len([t for t in state.L['tasks'].values() if t.get('repair_origin')]) == 1, 'recursive repair chain'
            assert spawner.next_task() is None, 'unchanged failed repair admitted again'
            return 'repair-bounded-without-recursion'
        lifecycle.revise(w['record'], repair['id'], 'independently verified brief/dependency repair', 'Implement clarified A',
                         summary='Implement the clarified independently verified behavior',
                         dependency_ids=[n for n in queues.records()[w['record']]['depends'] if n == 'fixture-tests'])
        if 'repair_origin_revision' in self.fault:
            lifecycle.stop('repair', 'transient transport loss', requeue=True)
            assert repair['runs'] == 1 and spawner.runnable(repair, {}), 'origin revision stranded repair handback'
            self.start(repair, 'repair-resumed')
        found = lifecycle.repair_evidence(repair)
        assert found['record_version'] == queues.records()[w['record']]['version']
        if self.fault.intersection(('repair_receipt_crash_before_save', 'repair_receipt_crash_after_save')):
            receipt = self.repair_receipt_restart(repair)
        else:
            receipt = lifecycle.submit(repair['id'], repair['agent'], 'complete', 'checked runnable handback')
        assert receipt['evidence']['repaired_record'] == w['record']
        state.L['agents'].clear()
        worker = spawner.next_task()
        assert worker['kind'] == 'item', 'checked repair stranded its worker continuation'
        self.worker = worker
        self.start(worker, 'worker-after-repair')
        submitted = self.node([self.refs['main']])
        self.refs[worker['branch']] = submitted
        lifecycle.submit(worker['id'], 'worker-after-repair', 'complete', 'useful repaired implementation',
                         {'commit': submitted, 'tests': landing.tests_of(worker), 'packet_tests': 1})
        state.L['agents'].pop('worker-after-repair')
        self.integration = integration = spawner.next_task()
        assert integration['kind'] == 'integrate', 'repaired worker skipped review'
        self.start(integration, 'integrator-after-repair')
        self.candidate = self.node([self.refs['main'], submitted])
        self.refs[integration['branch']] = self.candidate
        landing.land(integration['id'], self.candidate, 'integrator-after-repair')
        self.invariants()
        return 'repair-handback-and-landed'

    def repair_receipt_restart(self, repair):
        """Actual replacement adopts an unfinished repair or replays its durable receipt."""
        before_save = 'repair_receipt_crash_before_save' in self.fault
        self.durable = copy.deepcopy(state.L)
        self.fault.add('receipt_crash_before_save' if before_save else 'receipt_crash_after_save')
        body = {'caller': {'task': repair['id'], 'run': repair['agent']},
                'outcome': 'complete', 'detail': 'checked runnable handback'}
        try:
            api.dispatch('finish', body)
        except Crash:
            pass
        else:
            raise AssertionError('repair receipt persistence crash did not execute')
        previous = copy.deepcopy(self.durable)
        state.L.clear()
        self.fault, self.order = set(), []
        stopped, adopted = [], []
        self.keyfile.write_text(json.dumps({'coin': 'sim-coin', 'agents': {'repair': 'gateway-key'}}))
        real_adopt = keys.adopt
        def remember_adoption(*args):
            real_adopt(*args)
            adopted.append(args)
        with patch.object(subprocess, 'run', side_effect=lambda command, **kwargs: self.native_startup(command, {'repair': 403})), \
             patch.object(runs.keys, 'adopt', side_effect=remember_adoption), \
             patch.object(runs.opencode, 'active', return_value=True), \
             patch.object(runs.opencode, 'find_processes', return_value={'repair': [403]}), \
             patch.object(runs.opencode, 'stop_group', side_effect=lambda pid, **kw: stopped.append(pid)), \
             patch.object(daemon.snapshots, 'recover_transfers'), \
             patch.object(daemon.snapshots, 'forget_orphans'), \
             patch.object(daemon.snapshots, 'forget_untracked'):
            daemon.restore(previous)
        assert adopted == [('repair', 'background', 'gateway-key')] and not stopped, \
            'repair run or durable receipt lost startup delivery ownership'
        repair = state.L['tasks'][repair['id']]
        receipt = api.dispatch('finish', body)['receipt']
        assert api.dispatch('finish', body)['receipt'] == receipt, 'repair replay changed checked handback'
        assert repair['status'] == 'done' and repair['receipt'] == receipt
        settled = copy.deepcopy(repair)
        state.L['agents']['repair']['generation_tokens'] = repair['budget']['generation_tokens']
        recovery.enforce()
        assert 'repair' not in state.L['agents'] and repair == settled, 'receipt budget release reopened completed repair'
        receipt = api.dispatch('finish', body)['receipt']
        assert repair == settled, 'late repair replay reopened a settled assignment'
        assert len([t for t in state.L['tasks'].values()
                    if t.get('repair_origin') == repair['repair_origin']]) == 1, 'replacement duplicated repair'
        self.trace.append('repair-receipt-restored')
        return receipt

    def superseded_repair_trial(self):
        """A newer successful periodic pass obsoletes unadmitted historical repairs."""
        state.L['paused'] = False
        state.L['tasks'].pop(self.worker['id'])
        queues.records().pop(self.worker['record'])
        old = tasks.create('steward', tasks.SYSTEM, 'steward', 'Inspect project health', [5])
        self.start(old, 'old-steward')
        lifecycle.submit(old['id'], 'old-steward', 'blocked', 'inspection infrastructure failed')
        state.L['agents'].pop('old-steward')
        repair, created = tasks.request_repair(old)
        assert created and not repair['runs']
        running = 'repair_superseded_periodic' not in self.fault
        if running:
            self.start(repair, 'repair')
        self.clock += 1
        newer = tasks.create('steward', tasks.SYSTEM, 'steward', 'Inspect current project health', [5])
        self.start(newer, 'new-steward')
        api.dispatch('check-work', {'caller': {'task': newer['id'], 'run': 'new-steward'}})
        if 'repair_newer_pending' not in self.fault:
            api.dispatch('finish', {'caller': {'task': newer['id'], 'run': 'new-steward'},
                                  'outcome': 'blocked' if 'repair_newer_failed' in self.fault else 'complete',
                                  'detail': 'current inspection result',
                                  'scout_result': {'kind': 'no_action', 'checked_projects': ['sim']}})
            state.L['agents'].pop('new-steward')
        assert frontier.reason(old) is None, 'historical inspection remained current failure'
        if running:
            try:
                found = api.dispatch('finish', {'caller': {'task': repair['id'], 'run': 'repair'},
                                               'outcome': 'complete', 'detail': 'checked latest maintenance'})
            except ValueError as error:
                if 'repair_live_superseded' in self.fault:
                    raise AssertionError('newer successful maintenance had no checked repair handback') from error
                assert repair['receipt'] is None and repair['status'] == 'running'
                return 'unresolved-newer-maintenance-refused'
            if 'repair_live_superseded' not in self.fault:
                raise AssertionError('pending or failed newer maintenance accepted as repair')
            assert found['receipt']['evidence']['superseding_task'] == newer['id']
            assert found['receipt']['evidence']['receipt'] == newer['receipt']
            assert repair['status'] == 'done' and old['receipt']['disposition'] == 'blocked'
            return 'live-superseded-repair-closed'
        with patch.object(lifecycle, 'retire', return_value=False), \
             patch.object(lifecycle.snapshots, 'forget_orphans'):
            self.reconcile()
        assert not spawner.runnable(repair, {}), 'obsolete periodic repair remained runnable'
        assert repair.get('cancelled'), 'obsolete periodic repair kept a permanent waiting record'
        assert newer['receipt']['disposition'] == 'complete' and newer['status'] == 'done'
        return 'obsolete-periodic-repair-withdrawn'

    def dependency_arrival_trial(self):
        """An absent prerequisite can arrive without rewriting its dependent brief."""
        state.L['paused'] = False
        state.L['tasks'].pop(self.worker['id'])
        origin = queues.records()[self.worker['record']]
        origin['depends'] = ['prerequisite']
        repair, created = tasks.request_repair(origin)
        assert created
        running = 'repair_prerequisite_arrived' in self.fault
        if running:
            self.start(repair, 'repair')
        least, most = state.CONFIG['summary_words']
        words = 'Expose the missing prerequisite interface required by the queued implementation so its work can continue safely'.split()
        summary = ' '.join((words * (least // len(words) + 1))[:max(least, min(len(words), most))])
        body = {'project': self.project['name'], 'kind': 'queued', 'name': 'prerequisite',
                'stage': 'skeleton', 'brief': 'Summary: ' + summary + '\nExpose the prerequisite API'}
        if running:
            body['caller'] = {'task': repair['id'], 'run': 'repair'}
        api.dispatch('queue', body)
        assert origin['version'] == repair['repair_origin']['version'], 'fixture rewrote unchanged dependent'
        ready = queues.readiness(queues.live('sim'), queues.landed('sim'))
        assert ready['a'] == 'waiting' and ready['prerequisite'] == 'ready'
        if running:
            try:
                lifecycle.repair_evidence(repair)
            except ValueError as error:
                raise AssertionError('valid same-version dependency repair had no checked handback') from error
            lifecycle.submit(repair['id'], 'repair', 'complete', 'missing prerequisite queued and runnable')
            state.L['agents'].pop('repair')
        else:
            assert frontier.reason(origin) is None
            with patch.object(lifecycle, 'retire', return_value=False), \
                 patch.object(lifecycle.snapshots, 'forget_orphans'):
                self.reconcile()
            assert repair['status'] == 'waiting' and not repair['runs'], 'pending graph verification was lost'
            if self.fault.intersection(('repair_pending_graph_regression', 'repair_human_cancelled')):
                # A dependent prevents ordinary withdrawal of its prerequisite.
                # Revising that prerequisite can regress the graph without
                # changing this origin's assignment: a reachable control path.
                api.dispatch('revise', {'item': 'sim:prerequisite', 'reason': 'new prerequisite relation',
                                      'brief': 'Expose the prerequisite API\nDepends on: a'})
                assert origin['version'] == repair['repair_origin']['version']
                assert 'cycle' in frontier.reason(origin)
                spawner.refresh()
                assert tasks.request_repair(origin) == (repair, False), 'graph regression lost original repair route'
                assert len([t for t in state.L['tasks'].values()
                            if t.get('repair_origin') == repair['repair_origin']]) == 1, 'graph regression duplicated repair'
                if 'repair_human_cancelled' in self.fault:
                    api.dispatch('cancel', {'items': [repair['id']], 'reason': 'user withdraws this repair'})
                    durable = copy.deepcopy(state.L)
                    state.L.clear()
                    state.L.update(state.fresh(durable))
                    origin = queues.records()['sim:a']
                    repair = state.L['tasks'][repair['id']]
                    for _ in range(3):
                        spawner.refresh()
                    assert tasks.request_repair(origin) == (repair, False)
                    assert repair['status'] == 'failed' and repair.get('cancelled') and not repair['runs']
                    return 'human-repair-cancellation-retained'
                try:
                    lifecycle.repair_evidence(repair)
                except ValueError:
                    pass
                else:
                    raise AssertionError('regressed dependency cycle accepted as repaired')
            if 'repair_obstruction_cleared' in self.fault:
                assert not spawner.runnable(repair, {}), 'cleared obstruction wasted a controller run'
                next_work = spawner.next_task()
                assert next_work['item'] == 'prerequisite', 'cleared obstruction stranded productive work'
                return 'cleared-obstruction-progresses-without-repair'
            assert spawner.next_task() is repair, 'pending verification lost scheduler admission'
            self.start(repair, 'verification')
            if 'repair_pending_graph_regression' in self.fault:
                api.dispatch('revise', {'item': 'sim:prerequisite', 'reason': 'verified acyclic prerequisite',
                                      'brief': body['brief'],
                                      'caller': {'task': repair['id'], 'run': 'verification'}})
                with patch.object(lifecycle, 'retire', return_value=False), \
                     patch.object(lifecycle.snapshots, 'forget_orphans'):
                    self.reconcile()
            lifecycle.submit(repair['id'], 'verification', 'complete', 'origin dependency graph verified current')
            state.L['agents'].pop('verification')
        for item in ('prerequisite', 'a'):
            worker = spawner.next_task()
            assert worker and worker['kind'] == 'item' and worker['item'] == item, 'resolved graph did not drain in order'
            self.worker = worker
            run = 'worker-' + item
            self.start(worker, run)
            submitted = self.node([self.refs['main']])
            self.refs[worker['branch']] = submitted
            lifecycle.submit(worker['id'], run, 'complete', 'checked continuation',
                             {'commit': submitted, 'tests': landing.tests_of(worker), 'packet_tests': 1})
            state.L['agents'].pop(run)
            self.integration = integration = spawner.next_task()
            assert integration['kind'] == 'integrate', 'continuation skipped its receipt/landing gate'
            self.start(integration, 'integrator-' + item)
            self.candidate = self.node([self.refs['main'], submitted])
            self.refs[integration['branch']] = self.candidate
            landing.land(integration['id'], self.candidate, 'integrator-' + item)
            state.L['agents'].pop('integrator-' + item)
        self.invariants()
        assert origin.get('done') and queues.records()['sim:prerequisite'].get('done')
        if 'repair_pending_graph_regression' in self.fault:
            return 'regressed-pending-repair-drained'
        return 'same-version-dependency-repair-drained' if running else 'cleared-obstruction-drained'


def minimize(sim, faults, seed, original):
    """Delete faults while the same invariant failure remains reproducible."""
    smallest = list(faults)
    for fault in list(smallest):
        candidate = [f for f in smallest if f != fault]
        if not candidate:
            continue
        try:
            sim.trial(candidate, seed)
        except Exception as error:
            if type(error) is type(original) and str(error) == str(original):
                smallest = candidate
    return smallest


def run(cases=1000, seed=1, faults=None, pairs=False):
    rng, counts, failures = random.Random(seed), collections.Counter(), []
    started = time.perf_counter()
    sim = Simulation()
    independent = [f for f in sim.faults if f not in (
        'worker_blocked', 'revision', 'dependency_cycle', 'missing_dependency', 'held_dependency', 'two_workers',
        'receipt_crash_before_save', 'receipt_crash_after_save',
        'incorporate_cancel', 'incorporate_hold', 'incorporate_receipt_changed', 'manager_unresolved',
        'integration_resume_race', 'producer_metadata_failure', 'qualified_dependencies', 'migrate_qualified_dependencies')
        and not f.startswith(('adopt_', 'repair_', 'namespace_', 'observer_', 'artifact_', 'hidden_', 'admission_', 'authority_'))]
    schedules = list(itertools.permutations(independent, 2)) if pairs else None
    if schedules:
        cases = len(schedules)
    try:
        for n in range(cases):
            # Isolated queue/manager scenarios plus up to six simultaneous faults
            # scheduled at pre-validation, test, durability and publication boundaries.
            independent = [f for f in sim.faults if f not in (
                "worker_blocked", "revision", "dependency_cycle", "missing_dependency", "held_dependency", "two_workers",
                "receipt_crash_before_save", "receipt_crash_after_save",
                "incorporate_cancel", "incorporate_hold", "incorporate_receipt_changed", "manager_unresolved",
                "integration_resume_race", "producer_metadata_failure", "qualified_dependencies", "migrate_qualified_dependencies")
                and not f.startswith(('adopt_', 'repair_', 'namespace_', 'observer_', 'artifact_', 'hidden_', 'admission_', 'authority_'))]
            fault = schedules[n] if schedules else faults or (sim.faults[n] if n < len(sim.faults) else
                              rng.choice(sim.faults) if n % 5 == 0 else
                              rng.sample(independent, rng.randint(1, 6)))
            try:
                outcome = sim.trial(fault, seed + n)
                counts[outcome] += 1
            except Exception as error:
                counts["invariant-failure"] += 1
                if not any(f["fault"] == fault for f in failures):
                    trace = list(sim.trace)
                    reduced = minimize(sim, [fault] if isinstance(fault, str) else fault, seed + n, error)
                    failures.append({"seed": seed + n, "fault": fault, "minimal_faults": reduced,
                                     "error": repr(error), "trace": trace})
        elapsed = time.perf_counter() - started
        return {"seed": seed, "cases": cases, "seconds": elapsed, "cases_per_second": cases / elapsed,
                "outcomes": dict(counts), "failures": failures, "faults": list(sim.faults)}
    finally:
        sim.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pairs", action="store_true", help="Sweep every ordered pair of landing faults")
    parser.add_argument("--fault", action="append", choices=Simulation.faults,
                        help="Replay a fault combination; repeat for multiple faults")
    args = parser.parse_args()
    result = run(args.cases, args.seed, args.fault, args.pairs)
    rendered = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n")
    print(rendered)
    raise SystemExit(bool(result['failures']))
