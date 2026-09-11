---
verified_at: '2026-09-11T23:40:00+10:00'
verified_by: opencode /home/david
scope: project local
source: 'what/is/intended/live_capacity_contract.md; ecosystem/opencode_capacity.py; ecosystem/opencode_client.py; config/opencode-capabilities.json; git status --short --branch'
verification: Tasks 1 and 2 implemented and verified: 24 + 10 focused tests pass; full suite shows the same 19 pre-existing failures as the tree without the new files.
review_when: Recheck after the Task 3 observation-adapter commit or a priority change from David.
---

Plan Tasks 1 and 2 are done: `ecosystem/opencode_capacity.py`
(`effective_inference_capacity`, `launch_fingerprint`) and
`ecosystem/opencode_client.py`
(`qualified_opencode_capability`, `load_capability_catalogue`) with the
checked-in catalogue `config/opencode-capabilities.json` (1.18.30 -> 32000).
Focused tests: `python3 -m unittest discover -s tests -p
'test_opencode_capacity.py' -q` and `... -p 'test_opencode_client.py' -q`.

Next: plan Task 3, the fresh backend-capacity observation adapter — a narrow
projection in the current observation owners (`ecosystem/models.py`,
`ecosystem/context_layout.py`) producing
`observe_opencode_backend_capacity(...) -> dict | None`, bound to one backend
incarnation and suitable for the pure constructor; return explicit absence for
contradictions. Do not create a duplicate HTTP/process observer, edit the user
OpenCode JSON, replace the `opencode` symlink, activate a wrapper, restart
services, or change live model allocation; those remain later gated actions.
