---
verified_at: '2026-09-11T23:30:00+10:00'
verified_by: opencode /home/david
scope: project local
source: config/opencode-capabilities.json; ecosystem/opencode_client.py; tests/test_opencode_client.py; approved live-capacity plan Task 2
verification: Wrote and ran the focused tests for the qualification boundary; the checked-in catalogue resolves the installed 1.18.30 to its observed 32000-token ceiling.
review_when: Recheck when the OpenCode version, the catalogue shape, or the qualification probe changes.
---

Requalify OpenCode when `opencode --version` reports a version that has no
entry in `config/opencode-capabilities.json`; until then
`qualified_opencode_capability` raises and launch stays closed, with no
default capability.

1. Record the exact version identity: run
   `/home/david/.opencode/bin/opencode --version` and use the literal output
   (surrounding newline aside) as the catalogue key.
2. Establish the output ceiling with a bounded probe: a request-capture
   probe against the loopback Lemonade backend, or an authoritative client
   fact. Never infer the ceiling from `context / 3` or force a full-length
   live generation merely to prove a limit.
3. Add one entry to `config/opencode-capabilities.json` with exactly
   `maximum_output_tokens` (positive integer), `qualified_at` (date), and
   `evidence` (the version command and probe description; no session
   contents). Duplicate, unknown, or non-positive entries are rejected by
   `load_capability_catalogue`.
4. Verify: run
   `python3 -m unittest discover -s tests -p 'test_opencode_client.py' -q`
   (and `test_opencode_capacity.py`), then commit the catalogue and code
   together.

The catalogue is a capability record, not desired model policy; keep model
limits in their own owners.
