---
verified_at: '2026-09-12T01:52:04+10:00'
verified_by: opencode /home/david
scope: project local
source: 'what/is/intended/live_capacity_contract.md; ecosystem/opencode_capacity.py; ecosystem/opencode_client.py; config/opencode-capabilities.json; ecosystem/models.py; git status --short --branch'
verification: Tasks 1, 2, and 3 implemented and verified: 24 + 10 + 5 (adapter) + 1 (layout seam) focused tests pass; full suite shows the same 19 pre-existing failures as the tree without the new files.
review_when: Recheck after the Task 4 encoder commit or a priority change from David.
---

Plan Tasks 1, 2, and 3 are done: `ecosystem/opencode_capacity.py`
(`effective_inference_capacity`, `launch_fingerprint`),
`ecosystem/opencode_client.py`
(`qualified_opencode_capability`, `load_capability_catalogue`) with the
checked-in catalogue `config/opencode-capabilities.json` (1.18.30 -> 32000), and
the fresh backend-capacity observation adapter
`ecosystem/models.py` `observe_opencode_backend_capacity(...) -> dict | None`
(a pure incarnation-bound projection of one verified resident observation into
the constructor's record; explicit absence for contradictions). Focused tests:
`python3 -m unittest discover -s tests -p 'test_opencode_capacity.py' -q`,
`... -p 'test_opencode_client.py' -q`, and `... -p 'test_model_admission.py' -q`.

Next: plan Task 4, the one ephemeral OpenCode configuration encoder —
`ecosystem/inference_proxy.py` `opencode_environment(...)` producing an
anonymous config whose selected-model limits exactly equal the effective
capacity record; seed base config with excessive limits and prove only effective
values reach the memfd, keep credential population/ownership unchanged, add no
second config writer, and strip authoritative capacity claims from the base
managed catalogue (`config/executor-opencode.json`). Do not edit the user
OpenCode JSON beyond the managed base catalogue, replace the `opencode` symlink,
activate a wrapper, restart services, or change live model allocation; those
remain later gated actions.
