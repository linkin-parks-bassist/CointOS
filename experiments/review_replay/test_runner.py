"""Check the replay apparatus with actual fixture execution; not model-quality evidence."""
import json

import pytest

from experiments.review_replay import runner


def call(name, reason='The assertion does not reject the promised wrong behavior.'):
    return {'role': 'assistant', 'tool_calls': [{'id': name, 'type': 'function',
        'function': {'name': name, 'arguments': json.dumps({} if name == 'inspect_candidate'
                                                         else {'reason': reason})}}]}


@pytest.mark.parametrize('name', runner.FIXTURES)
def test_real_probe_and_decision_are_retained(tmp_path, name):
    fixture = runner.FIXTURES[name]
    replies = iter([call('inspect_candidate'), call(fixture['expected'])])
    result = runner.replay(tmp_path / name, fixture, lambda *a: next(replies), 'fixture')
    assert result['passed']
    assert result['observations'][0]['exit'] == 0
    assert 'packet: PASS' in result['observations'][0]['stdout']
    assert json.loads((tmp_path / name / 'result.json').read_text())['decision'] == result['decision']


def test_accepting_known_wrong_pipeline_fails_replay(tmp_path):
    replies = iter([call('inspect_candidate'), call('accept_packet')])
    result = runner.replay(tmp_path / 'bad', runner.FIXTURES['pipeline'], lambda *a: next(replies), 'fixture')
    assert not result['passed']
    assert result['observations'][0]['exit'] == 0


def test_no_decision_without_inspection_and_no_overwriting_evidence(tmp_path):
    with pytest.raises(ValueError, match='inspected evidence'):
        runner.replay(tmp_path / 'bad', runner.FIXTURES['pipeline'], lambda *a: call('return_packet'), 'fixture')
    with pytest.raises(FileExistsError):
        runner.replay(tmp_path / 'bad', runner.FIXTURES['pipeline'], lambda *a: call('return_packet'), 'fixture')
