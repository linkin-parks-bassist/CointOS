---
verified_at: '2026-09-11T23:05:00+10:00'
verified_by: opencode /home/david
scope: project local
source: 'what/is/intended/live_capacity_contract.md; ecosystem/opencode_capacity.py; tests/test_opencode_capacity.py; git status --short --branch'
verification: Task 1 implemented and verified: 24 focused tests pass; full suite shows the same 4 failures + 15 errors as the tree without the new files (pre-existing, unrelated).
review_when: Recheck after the Task 2 capability commit or a priority change from David.
---

Plan Task 1 (pure effective-capacity record) is done: `ecosystem/opencode_capacity.py`
implements `effective_inference_capacity(observation, client_capability, policy, now)`
plus `launch_fingerprint`, with fail-closed ValueError messages naming the
disagreeing facts; `tests/test_opencode_capacity.py` covers it (run with
`python3 -m unittest discover -s tests -p 'test_opencode_capacity.py' -q`).

Next: plan Task 2, the version-qualified OpenCode capability — create
`config/opencode-capabilities.json` and `ecosystem/opencode_client.py` producing
`qualified_opencode_capability(version_text, catalogue) -> dict` with no default for
unknown versions, plus `tests/test_opencode_client.py` and the requalification
procedure in `docs/operations.md`. Do not edit the user OpenCode JSON, replace the
`opencode` symlink, activate a wrapper, restart services, or change live model
allocation; those remain later gated actions.
