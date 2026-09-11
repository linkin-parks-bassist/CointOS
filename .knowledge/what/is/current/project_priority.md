---
verified_at: '2026-09-12T09:42:22+10:00'
verified_by: opencode /home/david
scope: project local
source: 'what/is/intended/live_capacity_contract.md; ecosystem/opencode_capacity.py; ecosystem/opencode_client.py; ecosystem/models.py; ecosystem/inference_proxy.py; ecosystem/inference_capacity.py validate_launch_capacity; ecosystem/executor.py launch_runner_round capacity preflight; config/opencode-capacity.json; git status --short --branch'
verification: Tasks 1-5 implemented and verified: focused suites test_opencode_capacity (24), test_opencode_client (10), test_inference_enforcement (45), test_inference_capacity (35 incl. 7 new validate_launch_capacity), test_executor (41) pass; full suite 747 tests shows the same 19 pre-existing failures as the tree without the new files (0 new, 12 added tests all green).
review_when: Recheck after the wrapper-integration/activation stage or a priority change from David.
---

Plan Tasks 1-5 are done: `ecosystem/opencode_capacity.py`
(`effective_inference_capacity`, `launch_fingerprint`),
`ecosystem/opencode_client.py`
(`qualified_opencode_capability`, `load_capability_catalogue`) with
`config/opencode-capabilities.json` (1.18.30 -> 32000), the observation adapter
`ecosystem/models.py` `observe_opencode_backend_capacity(...) -> dict | None`,
the ephemeral config encoder `ecosystem/inference_proxy.py`
`opencode_environment(...)` (consumes the validated record, strips static
capacity claims, rejects independent lease values; base catalogue
`config/executor-opencode.json` is names-only), and the final pre-spawn validation
`ecosystem/executor.py` `launch_runner_round` `capacity_preflight` phase +
`ecosystem/inference_capacity.py` `validate_launch_capacity` with the checked-in
policy `config/opencode-capacity.json`: it derives the effective record for the
routed model and fails the job back to `ready` (no spawn, no inference request) on
stale observation, changed incarnation, model mismatch, or lease context/output
above the live caps. Focused tests:
`python3 -m unittest discover -s tests -p 'test_opencode_capacity.py' -q`,
`... -p 'test_opencode_client.py' -q`, `... -p 'test_model_admission.py' -q`,
`... -p 'test_inference_enforcement.py' -q`, `... -p 'test_inference_capacity.py' -q`,
and `... -p 'test_executor.py' -q`.

Next: the independently verified wrapper-integration and activation stage. Do not
edit the user OpenCode JSON, replace the `opencode` symlink, activate a wrapper,
restart services, or change live model allocation; those remain later gated
actions.
