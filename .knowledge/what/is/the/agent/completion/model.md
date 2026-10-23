---
status: green
revised_at: "2026-10-24T02:31:18+11:00"
checked_at: '2026-10-24T02:31:19+11:00'
---

Completion is receipt-driven. Runner events describe execution; a run-owned typed receipt states completed, blocked or returned work. lifecycle.py checks artifacts and controls task/queue transitions. Output text, process exit and ancestry cannot settle work.

Receipts are idempotent for the same run and account; changed or foreign receipts refuse. Workers submit exact artifacts, integrators accept exact reviewed candidates, and maintenance publishes before completing. Failed submission returns concrete errors to the live run. A failed assignment gets one capable recovery Operator per assignment version. Holds, origins, dependencies and run authority remain binding.

Managers atomically create children and complete planning with handoff. Recovery replace checks an existing-item graph and landed controller artifacts before repointing dependents and completing atomically. Exact retries replay; invalid handoffs preserve tasks, runs and queue. Supersede remains nonterminal. correct-tests atomically completes recovery with an independent correction request; manager/ad-hoc callers stay active. Independent review activates corrected tests, preserving prior acceptance and implementation artifacts until then. Failed-parent backedges cannot count as runnable handoffs. Source and installed mechanism modules match.

Complete steward receipts declare scout_result: an owned runnable manager command, freshly checked enabled-project frontiers for no_action, or a specific personal decision. The scout-completion owner defines validation limits.

Transport observation preserves ambiguous OS queries and malformed-tail evidence. Terminal CLI output and actual MCP replies flush before retirement acknowledgement; MCP does not acknowledge inside captured CLI output. Surviving MCP processes retain launch code. Gateway pre-stop requests one real check and cannot settle work.

The focused receipt proof below establishes ownership/receipt mechanisms, not every clause or autonomous judgment. The broader recovery/publication replay is documented in how/to/test/cointos.md. Focused protocol/recovery/delivery owners define details; what/is/the/live/acceptance/evidence/for/cointos.md owns live acceptance.

Run ownership and receipt checks:

Proof:

```bash
cd "$(git rev-parse --show-toplevel)" && python3 -m unittest -q tests.test_agent_completion tests.test_authority_storage tests.test_run_admission
```
