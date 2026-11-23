---
status: green
revised_at: "2026-11-23T12:50:28+11:00"
---

No. `lookup` and `read` are universal; `grep`, `add`, `rewrite`, `renew`, `prove`, `audit`, `status`, `mv`, `combine`, and `rm` are granted only to the integrator, manager, gardener, tree-auditor, and operator roles.

`cointos/gateway.py` applies that split when the system prefix is first pinned, matching the OpenCode server prefix `knowledgetrees_` and stripping it before the role allowlist. A rename of the MCP tools must keep that prefix match current or every role silently receives the editing tools. `tests/test_prompt_date.py` covers both the ordinary and maintenance-role outcomes.
