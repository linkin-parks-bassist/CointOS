"""Reviewed test contracts and their corrections.

Acceptance is immutable evidence, not an assertion that a test can never be wrong.
A correction is another independently written and reviewed packet. Until it is
accepted the old packet remains binding. Acceptance switches dependent assignments
to the corrected contract together, preserving their implementation artifacts.
"""
from __future__ import annotations

from cointos import contracts, dependencies, git, queues
from cointos.state import L


def accepted(record: dict) -> str:
    commit = (record.get('done') or {}).get('commit')
    if record.get('stage') != 'test-contract' or not commit:
        raise ValueError('a correction must name an accepted test-contract packet')
    return commit


def current(record: dict) -> dict:
    """Resolve accepted corrections without erasing the original review evidence."""
    seen = set()
    while record.get('corrected_by'):
        key = queues.key(record)
        if key in seen:
            raise ValueError('test-contract correction cycle')
        seen.add(key)
        replacement = queues.records().get(record['corrected_by'])
        if replacement is None:
            raise ValueError('accepted test correction is missing: ' + record['corrected_by'])
        accepted(replacement)
        record = replacement
    return record


def propose(project: dict, packet: str, name: str, brief: str, *, by: str,
            summary: str, reliances: list[str], reason: str) -> dict:
    """Queue one correction of the exact accepted packet; replay returns its owner."""
    key = packet if ':' in packet else f"{project['name']}:{packet}"
    source = queues.records().get(key)
    if not source or source['project'] != project['name']:
        raise ValueError('name an accepted test packet in this project')
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('state the contract defect and evidence requiring correction')
    source = current(source)
    commit = accepted(source)
    correction = {'packet': queues.key(source), 'commit': commit, 'reason': reason.strip()}
    for record in queues.records().values():
        previous = record.get('correction') or {}
        if (previous.get('packet') == correction['packet'] and previous.get('commit') == commit
                and not record.get('done') and not record.get('replaced_by')):
            return record
    item = queues.add(project, 'queued', name, brief, 'test-contract',
                      dependency_ids=[source['item']], summary=summary, reliances=reliances)
    record = queues.records()[f"{project['name']}:{item}"]
    record.update(correction=correction, proposed_by=by)
    return record


def require_current(worker: dict) -> None:
    """A correction may replace only the exact contract its independent author saw."""
    correction = (queues.records().get(worker.get('record')) or {}).get('correction')
    if correction:
        source = queues.records().get(correction['packet'])
        if not source or source.get('corrected_by') or accepted(source) != correction['commit']:
            raise ValueError('the test contract changed while its correction was reviewed')


def require_changed_tests(worker: dict, repo: str, commit: str, rules: dict) -> None:
    correction = (queues.records().get(worker.get('record')) or {}).get('correction')
    if correction:
        require_current(worker)
        if not any(contracts.protected(path, rules) for path in git.changed(repo, correction['commit'], commit)):
            raise ValueError('a test-contract correction must change the accepted tests or their harness')


def activate(record: dict) -> list[str]:
    """Switch contract edges after review; the lifecycle refreshes the affected tasks."""
    correction = record.get('correction')
    if not correction:
        return []
    accepted(record)
    source = queues.records()[correction['packet']]
    if source.get('corrected_by') == queues.key(record):
        return []
    if source.get('corrected_by') or accepted(source) != correction['commit']:
        raise ValueError('the corrected contract is no longer current')
    changed = []
    for other in queues.records().values():
        if (other is record or other['project'] != record['project'] or other.get('done')
                or other.get('replaced_by') or source['item'] not in other['depends']):
            continue
        names = list(dict.fromkeys(record['item'] if n == source['item'] else n for n in other['depends']))
        other.update(depends=names, brief=dependencies.dependency_brief(other['brief'], names),
                     version=other['version'] + 1)
        changed.append(queues.key(other))
    source['corrected_by'] = queues.key(record)
    return changed


def pending(record: dict, candidates=None) -> list[dict]:
    """Unreviewed replacements of this assignment's contracts, excluding itself."""
    needed = {f"{record['project']}:{name}" for name in record.get('depends', [])}
    return [r for r in (queues.records().values() if candidates is None else candidates)
            if (r.get('correction') or {}).get('packet') in needed
            and queues.key(r) != queues.key(record) and not r.get('done') and not r.get('replaced_by')]


def continuations(record: dict) -> list[dict]:
    """Unheld corrections that can unblock this assignment's accepted contract edges."""
    return [r for r in pending(record) if not r.get('held_by')]
