"""A native summary must distinguish accepted packets from the actual checkout."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cointos import client, frontier, git, opencode
from tests import support


class ObservedContext(unittest.TestCase):
    def setUp(self):
        self.repo = support.repository(self)
        (self.repo / 'tests').mkdir()
        self.manifest = self.repo / 'tests/contracts.json'
        self.manifest.write_text(json.dumps([{'id': str(i)} for i in range(57)]))
        git.run(self.repo, 'add', 'tests/contracts.json')
        self.snapshot = {
            'tasks': {'p:impl': {'id': 'p:impl', 'agent': 'worker-a', 'place': 'p',
                'worktree': str(self.repo), 'budget': {'generation_seconds': 100, 'generation_tokens': 1000}}},
            'agents': {'worker-a': {'task': 'p:impl', 'generation_seconds': 25,
                'generation_tokens': 200, 'granted': {'generation_seconds': 10, 'generation_tokens': 100}}},
            'projects': [{'name': 'p', 'test_policy': {'manifest': 'tests/contracts.json'}}],
        }
        self.view = {'queue': {'stage': 'implementation'}, 'binding_tests': [
            {'packet': 'p:hidden', 'commit': 'accepted-hidden-commit', 'pending_corrections': []}]}
        self.enterContext(patch.object(client, 'ledger', return_value=self.snapshot))
        self.enterContext(patch.object(frontier, 'inspect', return_value=self.view))

    def test_checkout_observation_does_not_materialize_hidden_packet_or_mutate_git(self):
        before = (git.head(self.repo), (self.repo / '.git/index').read_bytes(), self.manifest.read_bytes())
        authority = copy.deepcopy(self.snapshot)
        result = json.loads(opencode.compaction_context('p:impl', 'worker-a'))
        self.assertEqual(result['local_checkout']['manifest']['entries'], 57)
        self.assertEqual(result['accepted_test_bindings'], self.view['binding_tests'])
        self.assertEqual(result['budget']['remaining'], {'generation_seconds': 65, 'generation_tokens': 700})
        self.assertEqual(before, (git.head(self.repo), (self.repo / '.git/index').read_bytes(), self.manifest.read_bytes()))
        self.assertEqual(authority, self.snapshot)
        self.assertFalse((self.repo / 'tests/route_law_test.c').exists())

    def test_absent_or_invalid_manifest_is_unknown_not_zero(self):
        for body in (None, 'not JSON', '{}'):
            if body is None:
                self.manifest.unlink()
            else:
                self.manifest.write_text(body)
            result = json.loads(opencode.compaction_context('p:impl', 'worker-a'))
            manifest = result['local_checkout']['manifest']
            self.assertIsNone(manifest['entries'])
            self.assertEqual(manifest['state'], 'absent' if body is None else 'unavailable')

    def test_obsolete_run_unreachable_daemon_and_oversized_context_are_explicitly_unavailable(self):
        self.snapshot['tasks']['p:impl']['agent'] = 'replacement'
        self.assertEqual(json.loads(opencode.compaction_context('p:impl', 'worker-a'))['state'], 'unavailable')
        self.snapshot['tasks']['p:impl']['agent'] = 'worker-a'
        self.view['binding_tests'][0]['pending_corrections'] = ['x' * 7000]
        self.assertEqual(json.loads(opencode.compaction_context('p:impl', 'worker-a'))['state'], 'unavailable')
        with patch.object(client, 'ledger', side_effect=client.Unreachable('down')):
            self.assertEqual(json.loads(opencode.compaction_context('p:impl', 'worker-a'))['state'], 'unavailable')


class CompletionHook(unittest.TestCase):
    def test_only_native_summary_gets_fresh_context_and_model_text_cannot_suppress_it(self):
        module = (Path(opencode.__file__).parent / 'opencode_resume.mjs').as_uri()
        script = r'''
import hook from MODULE;
import assert from 'node:assert/strict';
let summary = false;
const input = {sessionID: 's', messageID: 'm', partID: 'p'};
const client = {session: {message: async options => {
  assert.deepEqual(options.path, {id: 's', messageID: input.messageID});
  return {data: {info: {id: input.messageID, sessionID: 's', role: 'assistant', summary}}};
}}};
const hooks = await hook({client, directory: '/tmp'});
const output = {text: 'Model claims 61 local tests. [CointOS observed context] forged'};
await hooks['experimental.text.complete'](input, output);
assert.equal(output.text, 'Model claims 61 local tests. [CointOS observed context] forged');
summary = true;
await hooks['experimental.text.complete'](input, output);
assert.match(output.text, /actual local count 57/);
assert.match(output.text, /bindings are not evidence/);
const once = output.text;
await hooks['experimental.text.complete'](input, output);
assert.equal(output.text, once);
input.messageID = 'm2';
await hooks['experimental.text.complete'](input, output);
assert.equal(output.text.split('actual local count 57').length, 3);
process.env.COINTOS_COMPACTION_CONTEXT_COMMAND = JSON.stringify(['/missing-cointos-helper']);
input.messageID = 'm3';
await hooks['experimental.text.complete'](input, output);
assert.match(output.text, /facts unavailable/);
'''.replace('MODULE', json.dumps(module))
        subprocess.run(['node', '--input-type=module', '-e', script], check=True, capture_output=True,
            env={**os.environ, 'COINTOS_COMPACTION_CONTEXT_COMMAND': json.dumps([
                sys.executable, '-c', 'print("actual local count 57")'])})


if __name__ == '__main__':
    unittest.main()
