"""An agent's system prefix is pinned per task and identical across tasks: no clock rollover,
worktree, scope or skill location may change it."""
import json
from copy import deepcopy
from pathlib import Path
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
        self.assertNotIn("Sep 2", expected[0]["content"])
        self.assertIn("stated in your assignment", expected[0]["content"])
        self.assertIn("Today's date: Sun Sep 27 2026", before[0]["content"])
        self.assertIn("Task start date: Sun Sep 27 2026", prompts.launch_text(state.L["tasks"][self.tid], tasks.SYSTEM))

    def test_tasks_in_different_places_share_one_system_prefix(self):
        """Everything before the assignment must match token for token, or no fresh task can
        restore another's cached start."""
        other = tasks.create("steward", tasks.SYSTEM, "scout", "Elsewhere", [6])["id"]
        state.L["tasks"][other]["prompt_date"] = "Mon Sep 28 2026"
        state.L["agents"]["other"] = {"task": other}

        def environment(directory, git, date):
            return [{"role": "system", "content": "Tools and instructions\n<env>\n"
                     f"  Working directory: {directory}\n  Workspace root folder: {directory}\n"
                     f"  Is directory a git repo: {git}\n  Platform: linux\n  Today's date: {date}\n</env>"},
                    {"role": "user", "content": "Implement A"}]

        first = gateway.stable_environment(environment("/w/a", "yes", "Sun Sep 27 2026"), "agent")
        second = gateway.stable_environment(environment("/", "no", "Mon Sep 28 2026"), "other")
        self.assertEqual(first[0], second[0])
        self.assertIn("Platform: linux", first[0]["content"])

    def test_agents_never_list_claude_code_skills(self):
        from cointos import opencode
        env = opencode.environment(opencode.ROOT, {"task": state.L["tasks"][self.tid]})
        self.assertEqual(env["OPENCODE_DISABLE_CLAUDE_CODE_SKILLS"], "1")
        self.assertEqual(env["OPENCODE_EXPERIMENTAL_DISABLE_FILEWATCHER"], "1")

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
        self.assertNotIn("Working directory: /tmp/p", result[0]["content"])

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
        system = gateway.stable_environment(body["messages"], "agent")[0]["content"]
        expected = [n for n in (len((system + "|" + prefix).encode()) for prefix in prompts.shared_launch_tiers(task))
                    if n >= state.CONFIG["scheduler"]["shared_prefix_tokens"]]  # too-short starts are not worth a snapshot
        self.assertEqual(len(expected), 2)
        self.assertEqual(rendered["shared"], expected)
        self.assertEqual(rendered["shared"][-1], len((system + "|" + prompts.shared_launch_prefix(task)).encode()))
        self.assertEqual(renderer.call_count, 4)

    def test_coins_fixed_prompt_and_tools_are_a_shared_start(self):
        body = {"messages": [{"role": "system", "content": "You are Coin."}, {"role": "user", "content": "hi"}]}

        def render(config, model, conversation):
            if not any(message['role'] == 'user' for message in conversation['messages']):
                raise ValueError('No user query found in messages')
            text = "|".join(str(message.get("content", "")) for message in conversation["messages"])
            return {"tokens": list(text.encode()) + [999], "reader": {}}

        with patch.object(gateway.BACKEND, "render", side_effect=render):
            rendered = gateway.render_request(body, "coin", state.CONFIG["work_model"], {})
        self.assertEqual(rendered["shared"], [len("You are Coin.|".encode())])

    def test_continuation_is_rendered_only_once(self):
        state.L["tasks"][self.tid]["session"] = "session"
        body = {"messages": self.messages("Sun Sep 27 2026")}
        body["messages"][-1]["content"] = "Continue."
        with patch.object(gateway.BACKEND, "render", return_value={"tokens": [1, 2], "reader": {}}) as renderer:
            rendered = gateway.render_request(body, "agent", state.CONFIG["work_model"], {})
        self.assertNotIn("shared", rendered)
        renderer.assert_called_once()

    def test_fresh_run_marks_the_common_tools_before_role_specific_definitions(self):
        task = state.L['tasks'][self.tid]
        ordinary = {'type': 'function', 'function': {'name': 'read', 'description': 'common ' * 700}}
        role = {'type': 'function', 'function': {'name': 'cointos_finish', 'description': 'role contract'}}
        body = {'messages': self.messages('today'), 'tools': [role, ordinary]}
        body['messages'][-1]['content'] = prompts.launch_text(task, tasks.SYSTEM)

        def render(config, model, conversation):
            declarations = '\n'.join(t['function']['name'] + ':' + t['function']['description']
                                     for t in conversation.get('tools') or [])
            text = declarations + '\nEND_TOOLS\n' + '|'.join(m['content'] for m in conversation['messages'])
            return {'tokens': list(text.encode()) + [999], 'reader': {}}

        with patch.object(gateway.BACKEND, 'render', side_effect=render) as renderer:
            rendered = gateway.render_request(body, 'agent', state.CONFIG['work_model'], {})
        boundary = len(('read:' + ordinary['function']['description'] + '\n').encode())
        self.assertIn(boundary, rendered['shared'])
        self.assertGreaterEqual(boundary, state.CONFIG['scheduler']['shared_prefix_tokens'])
        self.assertEqual(renderer.call_args_list[0].args[2]['tools'], [ordinary, role])
        self.assertTrue(any(call.args[2]['tools'] == [ordinary] for call in renderer.call_args_list))
        self.assertEqual(body['tools'], [role, ordinary])


class ToolPinning(unittest.TestCase):
    def test_fresh_tool_partition_preserves_every_contract_and_order_within_groups(self):
        support.fresh_ledger(self)
        task = tasks.create('steward', tasks.SYSTEM, 'new', 'Assignment', [6])
        state.L['agents']['agent'] = {'task': task['id']}
        tools = [{'type': 'function', 'function': {'name': name, 'parameters': {'const': name}}}
                 for name in ('cointos_finish', 'read', 'cointos_task', 'bash')]
        before = deepcopy(tools)
        self.assertEqual(gateway.stable_tools(tools, 'agent'), [tools[i] for i in (1, 3, 0, 2)])
        self.assertEqual(tools, before)

    def test_fresh_runs_share_bash_contract_without_sharing_their_scratch(self):
        support.fresh_ledger(self)
        self.enterContext(patch.object(gateway, 'ROOT', Path('/installed')))
        first = tasks.create('steward', tasks.SYSTEM, 'first', 'First assignment', [6])
        second = tasks.create('steward', tasks.SYSTEM, 'second', 'Second assignment', [6])
        state.L['agents'].update(first={'task': first['id']}, second={'task': second['id']})

        def tools(agent):
            return [{'type': 'function', 'function': {'name': 'bash',
                     'description': f'Use `/installed/state/agents/{agent}/scratch/opencode` '
                                    'for temporary work outside the workspace. Keep every other rule.',
                     'parameters': {'type': 'object', 'properties': {'command': {'type': 'string'}},
                                    'required': ['command']}}}]

        raw = tools('first')
        before = deepcopy(raw)
        pinned = gateway.stable_tools(raw, 'first')
        self.assertEqual(pinned, gateway.stable_tools(tools('second'), 'second'))
        self.assertIn('$COINTOS_SCRATCH/opencode', pinned[0]['function']['description'])
        self.assertIn('Keep every other rule.', pinned[0]['function']['description'])
        self.assertEqual(pinned[0]['function']['parameters'], raw[0]['function']['parameters'])
        self.assertEqual(raw, before)
        # Relauching on a fresh run still resolves the current run's own path.
        from cointos import opencode
        for agent in ('first', 'second'):
            spec = {'task': {'id': agent, 'worktree': '/workspace'}}
            env = opencode.environment(Path('/installed/state/agents') / agent, spec)
            self.assertEqual(env['COINTOS_SCRATCH'], f'/installed/state/agents/{agent}/scratch')

    def test_existing_tool_prefix_and_non_bash_contracts_are_unchanged(self):
        support.fresh_ledger(self)
        self.enterContext(patch.object(gateway, 'ROOT', Path('/installed')))
        task = tasks.create('steward', tasks.SYSTEM, 'legacy', 'Assignment', [6])
        state.L['agents']['current'] = {'task': task['id']}
        ordinary = [{'type': 'function', 'function': {'name': 'bash',
                     'description': 'Use `/installed/state/agents/old/scratch/opencode` '
                                    'for temporary work outside the workspace.'}}]
        task['tool_context'] = 'legacy'
        state.L['system_contexts']['legacy'] = json.dumps(ordinary)
        self.assertEqual(gateway.stable_tools([], 'current'), ordinary)
        self.assertEqual(task['tool_context'], 'legacy')
        task.pop('tool_context')
        ordinary[0]['function']['name'] = 'read'
        self.assertEqual(gateway.stable_tools(ordinary, 'current'), ordinary)
        self.assertIs(gateway.stable_tools(ordinary, 'unmanaged'), ordinary)

    def test_cointos_contracts_refresh_while_other_tool_prefixes_remain_pinned(self):
        from cointos import gateway, state, tasks
        from tests import support
        support.fresh_ledger(self)
        project = support.project(self, support.repository(self))
        support.running(support.queued(project, "build"), "agent")
        ordinary = {"type": "function", "function": {"name": "read", "parameters": {"old": {}}}}
        first = [ordinary, {"type": "function", "function": {"name": "cointos_inbox", "parameters": {}}}]
        newer = [{"type": "function", "function": {"name": "read", "parameters": {"new": {}}}},
                 {"type": "function", "function": {"name": "cointos_inbox", "parameters": {"wait": {}}}},
                 {"type": "function", "function": {"name": "cointos_check_work", "parameters": {}}}]
        self.assertEqual(gateway.stable_tools(first, "agent"), first)
        refreshed = [ordinary, *newer[1:]]
        self.assertEqual(gateway.stable_tools(newer, "agent"), refreshed)
        self.assertEqual(gateway.stable_tools(newer, "agent"), refreshed)
        self.assertIsNone(gateway.stable_tools(None, "agent"))
        self.assertEqual(gateway.stable_tools(newer, "someone-else"), newer)


class VolatileStartup(unittest.TestCase):
    def test_a_tree_edit_does_not_change_the_prefix_new_tasks_share(self):
        from cointos import gateway
        from tests import support
        support.fresh_ledger(self)
        project = support.project(self, support.repository(self))
        support.running(support.queued(project, "one"), "first")
        support.running(support.queued(project, "two"), "second")
        startup = "=== local:where/am/i.md ===\nOrientation.\n=== kt dict ===\n{words}\n\nProof check required.\n"
        first = gateway.stable_environment([{"role": "system", "content": startup.format(words="alpha, beta")}], "first")
        second = gateway.stable_environment([{"role": "system", "content": startup.format(words="alpha, beta, named")}], "second")
        self.assertEqual(first, second)
        self.assertNotIn("kt dict", first[0]["content"])
        self.assertIn("Proof check required.", first[0]["content"])
