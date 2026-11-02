"""Stopping work that is too big for one agent, and starting any role directly."""
import copy
import unittest
from unittest.mock import patch

from cointos import api, cli, coin, kt_mcp, lifecycle, mcp, opencode, queues, schema, spawner, state, tasks
from cointos.config import ROOT
from tests import support


class Split(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        self.project = {"name": "p", "path": "/tmp/p", "main_branch": "main", "priority": 7, "enabled": True}
        self.enterContext(patch.dict(state.CONFIG, projects=[self.project]))
        self.enterContext(patch.object(lifecycle.opencode, "stop"))
        self.enterContext(patch.object(lifecycle.threading, "Thread"))
        queues.add(self.project, "queued", "huge", "Do six things.", "implementation")
        self.worker = tasks.create("item", self.project, "huge", "Do six things.", [4, 7], item="huge", record_version=1)
        support.running(self.worker, "worker-1", worktree=False)
        queues.add(self.project, "queued", "other", "Unrelated.", "implementation")
        self.other = tasks.create("item", self.project, "other", "Unrelated.", [4, 7], item="other", record_version=1)
        support.running(self.other, "worker-2", worktree=False)

    def test_it_stops_only_this_work_and_a_manager_replaces_it(self):
        queues.add(self.project, "queued", "after", "Depends: huge", "implementation", dependency_ids=["huge"])
        result = api.dispatch("split", {"task": self.worker["id"], "reason": "six sections"})
        self.assertTrue(result["ok"])
        self.assertNotIn("worker-1", state.L["agents"])
        self.assertIn("worker-2", state.L["agents"])
        self.assertEqual(self.other["status"], "running")
        records = queues.records()
        manager = records[result["task"]]
        self.assertEqual(manager["kind"], "command")
        self.assertIn("Do six things.", manager["brief"])
        self.assertIn(self.worker["branch"], manager["brief"])
        self.assertEqual(records["p:huge"]["replaced_by"], [result["item"]])
        self.assertEqual(records["p:after"]["depends"], [result["item"]])

    def test_no_recovery_operator_is_sent_after_a_split(self):
        api.dispatch("split", {"task": self.worker["id"], "reason": "big"})
        spawner.repair_work({"p": list(queues.records().values())})
        self.assertFalse([t for t in state.L["tasks"].values() if t.get("repair_origin")])

    def test_naming_its_first_responder_splits_the_assignment_and_stops_both(self):
        lifecycle.stop("worker-1", "budget", requeue=False)
        operator, _ = tasks.request_repair(self.worker)
        self.assertEqual(operator["role"], "first-responder")
        support.running(operator, "operator-1", worktree=False)
        result = api.dispatch("split", {"task": operator["id"], "reason": "going nowhere"})
        self.assertEqual(result["replaces"], self.worker["id"])
        self.assertNotIn("operator-1", state.L["agents"])
        self.assertIn("worker-2", state.L["agents"])
        self.assertEqual(operator["status"], "failed")

    def test_an_exhausted_worker_gets_a_first_responder_not_an_automatic_split(self):
        with patch.object(lifecycle.schema, "fresh_limit", return_value=0):
            lifecycle.retry_fresh("worker-1", "generation budget reached", "packet")
        spawner.repair_work({"p": list(queues.records().values())})
        responders = [t for t in state.L["tasks"].values() if t.get("repair_origin")]
        self.assertEqual([(t["kind"], t["role"]) for t in responders], [("first-response", "first-responder")])
        self.assertFalse(queues.records()["p:huge"].get("replaced_by"))

    def test_a_first_responder_that_runs_out_splits_an_implementer_once(self):
        lifecycle.stop("worker-1", "budget", requeue=False)
        responder, _ = tasks.request_repair(self.worker)
        support.running(responder, "responder-1", worktree=False)
        with patch.object(lifecycle.schema, "fresh_limit", return_value=0):
            lifecycle.retry_fresh("responder-1", "generation budget reached", "packet")
        scanned = {"p": copy.deepcopy(list(queues.records().values()))}
        spawner.repair_work(scanned)
        self.assertEqual(len(queues.records()["p:huge"]["replaced_by"]), 1)
        self.assertFalse(responder["exhausted"])
        self.assertIn("worker-2", state.L["agents"])

    def test_a_held_operator_splits_and_names_the_uncommitted_checkout(self):
        operator = tasks.request_operator("big", "Do everything.", "p", ["standard"], None, None)
        support.running(operator, "operator-2", worktree=False)
        result = api.dispatch("split", {"task": operator["id"], "reason": "huge"})
        brief = queues.records()[result["task"]]["brief"]
        self.assertIn("Do everything.", brief)
        self.assertIn(operator["worktree"], brief)
        self.assertIn("uncommitted", brief)
        self.assertNotIn("operator-2", state.L["agents"])
        self.assertIn("worker-1", state.L["agents"])
        self.assertIn("worker-2", state.L["agents"])

    def test_a_system_operator_has_no_manager_and_is_left_running(self):
        operator = tasks.request_operator("sys", "Do a thing.", None, ["standard"], None, None)
        support.running(operator, "operator-3", worktree=False)
        with self.assertRaisesRegex(ValueError, "registered project"):
            lifecycle.split(operator["id"], "big", "user")
        self.assertIn("operator-3", state.L["agents"])

    def test_repeated_splits_get_distinct_managers(self):
        first = lifecycle.split(self.worker["id"], "big", "user")
        queues.records()["p:huge"]["replaced_by"] = None
        self.assertNotEqual(lifecycle.split(self.worker["id"], "still big", "user")["item"], first["item"])

    def test_other_stages_refuse_and_get_a_first_responder(self):
        queues.add(self.project, "queued", "tests", "Write a test.", "skeleton")
        author = tasks.create("item", self.project, "tests", "Write a test.", [4, 7], item="tests", record_version=1)
        support.running(author, "author-1", worktree=False)
        with self.assertRaisesRegex(ValueError, "not an implementer"):
            lifecycle.split(author["id"], "big", "user")
        self.assertIn("author-1", state.L["agents"])
        self.assertFalse(queues.records()["p:tests"].get("replaced_by"))
        with patch.object(lifecycle.schema, "fresh_limit", return_value=0):
            lifecycle.retry_fresh("author-1", "generation budget reached", "packet")
        spawner.repair_work({"p": list(queues.records().values())})
        self.assertFalse(queues.records()["p:tests"].get("replaced_by"))
        self.assertEqual([t["repair_origin"]["task"] for t in state.L["tasks"].values() if t.get("repair_origin")], ["p:tests"])

    def test_work_with_no_queue_assignment_refuses_without_stopping_anything(self):
        steward = tasks.create("steward", tasks.SYSTEM, "scout", "Look.", [6])
        support.running(steward, "steward-1", worktree=False)
        with self.assertRaises(ValueError):
            lifecycle.split(steward["id"], "big", "user")
        self.assertIn("steward-1", state.L["agents"])


class AnyRole(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        self.project = {"name": "p", "path": "/tmp/p", "main_branch": "main", "priority": 7, "enabled": True}
        self.enterContext(patch.dict(state.CONFIG, projects=[self.project]))

    def test_manager_and_worker_are_queued_in_their_project(self):
        manager = api.dispatch("run-agent", {"role": "manager", "name": "goal", "brief": "Build it.", "project": "p"})
        worker = api.dispatch("run-agent", {"role": "worker", "name": "piece", "brief": "One bit.", "project": "p"})
        self.assertEqual(queues.records()[manager["task"]]["kind"], "command")
        self.assertEqual(queues.records()[worker["task"]]["kind"], "queued")

    def test_a_manager_without_a_project_says_how_to_get_one(self):
        with self.assertRaisesRegex(api.ApiError, "project_new"):
            api.run_agent({"role": "manager", "name": "goal", "brief": "Build it."})

    def test_system_roles_take_the_brief(self):
        for role, kind in (("steward", "steward"), ("test-auditor", "test-audit")):
            started = api.dispatch("run-agent", {"role": role, "name": f"look-{kind}", "brief": "Look here."})
            task = state.L["tasks"][started["task"]]
            self.assertEqual((task["kind"], task["brief"]), (kind, "Look here."))

    def test_an_integrator_needs_reviewed_work(self):
        with self.assertRaisesRegex(ValueError, "reviewed worker"):
            api.run_agent({"role": "integrator", "name": "land", "brief": "Land.", "task": "p:none"})

    def test_a_tree_role_names_its_tree(self):
        with self.assertRaisesRegex(ValueError, "needs project"):
            api.run_agent({"role": "tree-auditor", "name": "audit", "brief": "Audit.", "project": "nope"})

    def test_unknown_roles_and_agent_callers_are_refused(self):
        with self.assertRaisesRegex(api.ApiError, "unknown role"):
            api.run_agent({"role": "emperor", "name": "x", "brief": "x"})
        task = tasks.create("steward", tasks.SYSTEM, "scout", "Look.", [6])
        support.running(task, "steward-1", worktree=False)
        with self.assertRaises(api.ApiError):
            api.run_agent({"role": "manager", "name": "x", "brief": "x", "project": "p", "caller": support.caller(task, "steward-1")})


class CoinTools(unittest.TestCase):
    def test_coin_gets_every_knowledge_tool(self):
        names = ["kt_read", "kt_rm", "kt_mv", "kt_undo", "kt_access_request", "kt_access_confirm", "kt_access_revoke"]
        knowledge = {"tools": [{"function": {"name": n}} for n in names], "names": set(names)}
        _, tools = coin.system_prompt(knowledge)
        self.assertLessEqual(set(names), {t["function"]["name"] for t in tools})
        self.assertFalse(hasattr(kt_mcp, "EXCLUDED"))

    def test_dispatch_offers_every_role_and_split_exists(self):
        offered = {t["function"]["name"]: t["function"] for t in coin.TOOLS}
        roles = set(offered["dispatch"]["parameters"]["properties"]["role"]["enum"])
        self.assertEqual(roles, {spec["role"] for spec in __import__("cointos.schema").schema.KINDS.values()})
        self.assertIn("split_work", offered)
        self.assertEqual(coin.agent_request({"name": "a", "brief": "b", "role": "manager", "project": "p"})["role"], "manager")


class FirstResponder(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)
        self.project = {"name": "p", "path": "/tmp/p", "main_branch": "main", "priority": 7, "enabled": True}
        self.enterContext(patch.dict(state.CONFIG, projects=[self.project]))
        queues.add(self.project, "queued", "job", "Do it.", "implementation")
        self.worker = tasks.create("item", self.project, "job", "Do it.", [4, 7], item="job", record_version=1)
        self.worker.update(status="failed", note="generation budget reached")
        self.responder, _ = tasks.request_repair(self.worker)

    def test_it_is_a_distinct_role_with_a_small_budget_that_dispatches(self):
        self.assertEqual(self.responder["role"], "first-responder")
        self.assertEqual(self.responder["budget"], schema.budget(state.CONFIG, role="first-responder"))
        self.assertLess(self.responder["budget"]["generation_tokens"], schema.budget(state.CONFIG, role="operator")["generation_tokens"])
        self.assertIn("dispatch", self.responder["brief"])
        self.assertNotIn("Restore progress", self.responder["brief"])
        self.assertTrue((ROOT / "roles/first-responder.md").is_file())

    def test_its_edit_tools_are_off_but_it_keeps_its_controls(self):
        permission = opencode.settings(state.CONFIG, "key", self.responder, [])["permission"]
        self.assertEqual(permission["edit"]["*"], "deny")
        self.assertFalse([path for path, rule in permission["edit"].items() if rule == "allow"])
        self.assertTrue(api.controls_project(self.responder, "p"))

    def test_it_can_call_in_an_operator_without_spending_its_own_budget(self):
        support.running(self.responder, "responder-1", worktree=False)
        agent = state.L["agents"]["responder-1"]
        helper = tasks.request_operator("fix", "Fix the machine.", "p", ["standard"], None, None, (self.responder, agent))
        self.assertEqual(helper["role"], "operator")
        self.assertFalse(agent.get("granted"))

    def test_it_can_dispatch_every_role_except_coin_and_itself(self):
        support.running(self.responder, "responder-1", worktree=False)
        caller = support.caller(self.responder, "responder-1")
        started = api.run_agent({"role": "manager", "name": "cut-up", "brief": "Decompose it.", "project": "p", "caller": caller})
        self.assertEqual(queues.records()[started["task"]]["kind"], "command")
        started = api.run_agent({"role": "worker", "name": "piece", "brief": "Summary: write one small piece of the parser here\nOne bit.", "project": "p", "stage": "skeleton", "caller": caller})
        self.assertEqual(queues.records()[started["task"]]["stage"], "skeleton")
        for role, kind in (("steward", "steward"), ("test-auditor", "test-audit")):
            started = api.run_agent({"role": role, "name": f"call-{kind}", "brief": "Look.", "caller": caller})
            self.assertEqual(state.L["tasks"][started["task"]]["kind"], kind)
        self.assertEqual(state.L["tasks"][api.run_agent({"name": "fixer", "brief": "Fix it.", "project": "p", "caller": caller})["task"]]["role"], "operator")
        with self.assertRaisesRegex(api.ApiError, "does not call another"):
            api.run_agent({"role": "first-responder", "name": "x", "brief": "x", "task": self.worker["id"], "caller": caller})

    def test_coin_and_agents_have_the_identical_tool(self):
        coins = next(t["function"] for t in coin.TOOLS if t["function"]["name"] == "dispatch")
        agents = mcp.TOOLS["dispatch"]
        self.assertEqual(coins["description"], agents[1])
        self.assertEqual(coins["parameters"]["properties"], agents[2])
        self.assertEqual(coins["parameters"]["required"], agents[3])
        self.assertIn("first-responder", agents[0])
        self.assertNotIn("operator", mcp.TOOLS)
        self.assertNotIn("coin", agents[2]["role"]["enum"])
        self.assertEqual(set(agents[2]["role"]["enum"]), {spec["role"] for spec in schema.KINDS.values()})

    def test_who_calls_decides_what_it_may_start(self):
        steward = tasks.create("steward", tasks.SYSTEM, "scout", "Look.", [6])
        support.running(steward, "steward-1", worktree=False)
        with self.assertRaisesRegex(api.ApiError, "only the user and First Responders"):
            api.run_agent({"role": "manager", "name": "x", "brief": "x", "project": "p", "caller": support.caller(steward, "steward-1")})
        self.assertTrue(api.run_agent({"role": "manager", "name": "by-user", "brief": "Goal.", "project": "p"})["ok"])

    def test_tool_arguments_reach_the_cli_for_every_field(self):
        argv = mcp.dispatch_argv({"name": "n", "brief": "b", "role": "worker", "project": "p", "stage": "skeleton", "task": "t",
                                  "abilities": ["control", "network"], "reasoning_effort": "low", "generation_tokens": 5,
                                  "station": {"tools": ["x"]}})
        args = cli.parser().parse_args(argv)
        self.assertEqual((args.role, args.project, args.stage, args.task, args.ability, args.reasoning_effort, args.tool),
                         ("worker", "p", "skeleton", "t", ["control", "network"], "low", ["x"]))

    def test_the_user_can_replace_a_leftover_operator_with_a_first_responder(self):
        self.responder.update(role="operator", kind="operator", admission_hold="paused by the user")
        started = api.run_agent({"role": "first-responder", "name": "x", "brief": "x", "task": self.worker["id"]})
        fresh = state.L["tasks"][started["task"]]
        self.assertEqual((fresh["role"], fresh["repair_origin"]["task"]), ("first-responder", self.worker["record"]))
        self.assertEqual(self.responder["status"], "failed")
        self.assertNotIn("repair_origin", self.responder)

    def test_coin_cannot_be_dispatched_by_anyone(self):
        self.assertNotIn("coin", {spec["role"] for spec in schema.KINDS.values()})
        support.running(self.responder, "responder-1", worktree=False)
        for body in ({}, {"caller": support.caller(self.responder, "responder-1")}):
            with self.assertRaisesRegex(api.ApiError, "unknown role"):
                api.run_agent({"role": "coin", "name": "x", "brief": "x", **body})
        self.assertTrue((ROOT / "roles/coin.md").is_file())

    def test_an_operator_stays_a_general_agent(self):
        text = (ROOT / "roles/operator.md").read_text()
        self.assertNotIn("recovery controller", text)
        self.assertIn("First Responder", text)
