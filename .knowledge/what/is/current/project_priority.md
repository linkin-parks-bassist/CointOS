---
verified_at: '2026-09-12T02:10:00+10:00'
verified_by: opencode /home/david
scope: project local
source: 'what/is/intended/live_capacity_contract.md; ecosystem/opencode_capacity.py; ecosystem/opencode_client.py; ecosystem/models.py; ecosystem/inference_proxy.py; git status --short --branch'
verification: Tasks 1-4 implemented and verified: 24 (capacity) + 10 (client) + 5 (adapter) + 1 (layout seam) + 45 (enforcement incl. 4 new encoder) focused tests pass; full suite 735 tests shows the same 19 pre-existing failures as the tree without the new files.
review_when: Recheck after the Task 5 managed-launch validation commit or a priority change from David.
---

Plan Tasks 1-4 are done: `ecosystem/opencode_capacity.py`
(`effective_inference_capacity`, `launch_fingerprint`),
`ecosystem/opencode_client.py`
(`qualified_opencode_capability`, `load_capability_catalogue`) with
`config/opencode-capabilities.json` (1.18.30 -> 32000), the observation adapter
`ecosystem/models.py` `observe_opencode_backend_capacity(...) -> dict | None`,
and the ephemeral config encoder `ecosystem/inference_proxy.py`
`opencode_environment(...)` (consumes the validated record, strips static
capacity claims, rejects independent lease values; base catalogue
`config/executor-opencode.json` is names-only). Focused tests:
`python3 -m unittest discover -s tests -p 'test_opencode_capacity.py' -q`,
`... -p 'test_opencode_client.py' -q`, `... -p 'test_model_admission.py' -q`,
and `... -p 'test_inference_enforcement.py' -q`.

Next: plan Task 5, validate managed launches against live capacity —
`ecosystem/executor.py` wires the preflight at the final pre-spawn boundary,
consuming the admitted inference lease, a fresh observed backend record, and the
qualified OpenCode capability to produce the validated effective record before
`opencode_environment`, with no child process or inference request on
disagreement (stale evidence, changed incarnation, model mismatch, lease context
above live cap, lease output above the 32000 ceiling all fail closed). Do not
edit the user OpenCode JSON, replace the `opencode` symlink, activate a wrapper,
restart services, or change live model allocation; those remain later gated
actions.
