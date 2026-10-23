---
status: green
revised_at: "2026-10-22T07:44:32+11:00"
---

Complete steward receipts require structured scout_result; report wording is not parsed. MCP finish exposes kind no_action, manager_handoff or user_decision; CLI --scout-result-json passes the same object. Blocked receipts need no scout result.

manager_handoff names the exact PROJECT:ITEM command queued by this steward. lifecycle.scout_evidence checks its retained command record, proposer, absence of holds, nonblocked state and frontier prerequisites. Missing/foreign commands, dead handoffs and local user alerts refuse completion. Already-completed manager commands remain valid.

Before no_action, scouts call cointos_check_work without a draft. It supplies every enabled project's whole accepted Git plan, active queue and recent acceptance records, independently of the editor checkout. The daemon records the reviewed refs, plan blobs and queue facts for that run. Missing review, unavailable plans and changed frontiers refuse completion. checked_projects names every enabled project exactly once. Registry maintenance follows the same rule. The model must still read and judge the evidence.

user_decision names a specific question needing personal authority. Managerial planning of approved work belongs to a handoff. Receipt evidence retains the result; the checked receipt also enqueues the complete question for durable user delivery. Exact receipt retries do not enqueue it again. Routine alerts remain dashboard-only. Test-layer, ordering and implementation choices are engineering judgment, not personal-authority decisions.

The validator proves authority, inventory and currentness, not semantic completion. MiniCPM scout 48 completed after a local alert instead of a command. Typed handoff worked in ordinary scout 49; scout 52 subsequently declared no_action despite unfinished accepted-plan steps. With accepted-plan preflight, scout 53 independently queued pigen:plan-t10-golden-landing. Its resumed Qwen manager verified that the T10 tests were already landed and completed without duplicate worker work. It could not update the stale plan because the construction sandbox denied the knowledge-tree state database. how/does/cointos/confine/construction/writes.md owns that repaired permission defect. Neither the valid handoff nor the manager's correct no-op proves sustained whole-plan advancement.

Evidence: lifecycle.py, api.py, cli.py, mcp.py, roles/steward.md and queue/transport/idempotence tests in test_handoffs.py, test_mcp.py and test_agent_completion.py. Tests cover absent reviews, accepted/editor plan disagreement and frontier changes. The complete source suite, local proofs and runtime checks pass. Sustained unattended quality remains open.
