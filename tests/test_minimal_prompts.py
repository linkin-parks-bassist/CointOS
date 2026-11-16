"""Launch size and stage isolation are user-facing prompt contracts."""
import unittest

from cointos import prompts, schema, state, tasks
from tests import support


class MinimalPrompts(unittest.TestCase):
    def setUp(self):
        support.fresh_ledger(self)

    def test_every_role_has_a_small_shared_launch(self):
        for role in {s['role'] for s in schema.KINDS.values()}:
            stages = schema.STAGES if role == 'worker' else (None,)
            for stage in stages:
                with self.subTest(role=role, stage=stage):
                    text = prompts.shared_launch_prefix({'role': role, 'stage': stage})
                    self.assertLessEqual(len(text.split()), 260)
                    title = role.replace('-', ' ').title()
                    self.assertTrue(text.startswith(f'You are an autonomous CointOS {title}.\n\n# Your role\n\n'))
                    self.assertIn((prompts.ROLES / f'{role}.md').read_text(), text)
                    if role != 'supervisor':
                        self.assertIn('Write briefs in a few sentences', text)
        self.assertLessEqual(len((prompts.ROLES / 'coin.md').read_text().split()), 260)

    def test_supervisor_receives_only_its_current_job(self):
        ordinary = tasks.create('supervise', tasks.SYSTEM, 'check', 'Subject: p:work.', [1], supervises='p:work')
        split = {**ordinary, 'must_split': True, 'brief': 'Split p:work; files preserved.'}
        normal_text = prompts.launch_text(ordinary, tasks.SYSTEM)
        split_text = prompts.launch_text(split, tasks.SYSTEM)
        self.assertNotIn('split', normal_text.lower())
        self.assertNotIn('cointos_handoff', normal_text)
        self.assertNotIn('no action', split_text)
        self.assertNotIn('steer', split_text)
        self.assertNotIn('finish --complete', split_text)
        self.assertIn('exactly two', split_text)
        for text in (normal_text, split_text):
            self.assertNotIn('budget', text.lower())
            self.assertNotIn('generation seconds', text)
            self.assertNotIn('Accepted hidden tests', text)

    def test_supervisor_launch_does_not_copy_subject_instructions(self):
        subject = tasks.create('operator', tasks.SYSTEM, 'subject', 'Inspect a file.', [1])
        subject.update(role='worker', stage='implementation')
        supervisor = tasks.create('supervise', tasks.SYSTEM, 'check-worker', 'Check subject.', [1], supervises=subject['id'])
        for task in (supervisor, {**supervisor, 'must_split': True}):
            text = prompts.launch_text(task, tasks.SYSTEM)
            self.assertNotIn((prompts.ROLES / 'worker.md').read_text().strip(), text)
            self.assertNotIn("Subject's current role instructions", text)

    def test_worker_receives_only_its_stage_instructions(self):
        author = prompts.shared_launch_prefix({'role': 'worker', 'stage': 'test-contract'})
        implementer = prompts.shared_launch_prefix({'role': 'worker', 'stage': 'implementation'})
        self.assertIn('Author one reviewed-map scenario', author)
        self.assertNotIn('Author one reviewed-map scenario', implementer)
        self.assertNotIn('hidden', implementer.lower())
        self.assertNotIn('Do not seek hidden tests', author)

    def test_small_complete_launch_and_no_silent_requirement_truncation(self):
        task = tasks.create('operator', tasks.SYSTEM, 'inspect', 'Inspect the named service and report its exit status.', [1], abilities=['standard'])
        text = prompts.launch_text(task, tasks.SYSTEM)
        self.assertLessEqual(len(text.split()), 700)
        self.assertIn('Finish with the appropriate CointOS tool.', text)
        task['brief'] = 'MANDATORY REQUIREMENT. ' * 1000
        self.assertIn(task['brief'], prompts.launch_text(task, tasks.SYSTEM))

class StartupSources(unittest.TestCase):
    def test_known_harness_essays_are_replaced_without_losing_project_instructions(self):
        content = ('You are opencode, an interactive CLI tool. Generic Git advice.\n'
                   'Instructions from: PROJECT_RULES\nPreserve the user specification.\n'
                   '<env>\nPlatform: linux\n</env>\n'
                   '<mcp_instructions><server name="knowledgetrees">Long global history</server></mcp_instructions>'
                   '<available_skills>Unrelated personal skills</available_skills>')
        shown = prompts.system_context(content)
        self.assertIn('Preserve the user specification.', shown)
        for absent in ('Generic Git advice', 'Long global history', 'Unrelated personal skills'):
            self.assertNotIn(absent, shown)
        self.assertEqual(prompts.system_context('Knowledge-tree startup: whole root'), '')

    def test_implementer_tools_do_not_advertise_test_bindings(self):
        import json
        from cointos import mcp
        tools = mcp.catalogue('worker')
        self.assertNotIn('hidden', json.dumps(tools).lower())
        check = next(t for t in tools if t['name'] == 'check_work')
        self.assertEqual(check['inputSchema']['properties'], {})
