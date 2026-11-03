import unittest
from unittest.mock import patch

from cointos import prompts


def record(item, **fields):
    return {'project': 'p', 'item': item, 'depends': [], 'summary': f'{item} summary', **fields}


class UnboundTests(unittest.TestCase):
    def test_a_manager_sees_hidden_tests_nothing_depends_on(self):
        records = {r['item']: r for r in [
            record('old-line-1', stage='test-contract', done={'at': 1, 'via': 'tests'}),
            record('bound-line', stage='test-contract', done={'at': 2, 'via': 'tests'}),
            record('impl', stage='implementation', depends=['bound-line']),
            record('visible', stage='test-contract', done={'at': 3, 'via': 'landing'}),
            record('dropped-dependent', stage='implementation', depends=['old-line-1'], replaced_by='x'),
        ]}
        with patch.object(prompts.queues, 'records', return_value=records):
            self.assertEqual([r['item'] for r in prompts.unbound_tests('p')], ['old-line-1'])


if __name__ == '__main__':
    unittest.main()
