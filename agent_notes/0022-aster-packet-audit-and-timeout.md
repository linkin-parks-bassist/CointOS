# Packet audit and next dispatch — Aster (Astra), 2026-09-08

Audited completed batch before reusing eight slots. A1 budget audit and current H1
evaluator report PASS; independently reran A1/H1/existing parent-reservation tests:
13 passed. Budget race audit reports a deterministic lost child reservation between
unlocked adoption and parent write. Existing green regression covers only the
pre-read case; serialize that transaction with enqueue_child's task-enqueue.lock.
R4 scoped release review reports PASS for its two identity/EOF ordering cases at
its older worktree; this does not establish complete current liveness-contract
coverage. P1 audit correctly found its requested implementation absent at c7e1505.

Timeout fix2 and classifier attempts ended in CURL streaming errors with clean
worktrees and no commits. They are not accepted fixes. Their process exit code 0
was misleading; corrected terminal-error job outcomes to failed and retained JSONL.
R4's completed old runner was closed using the reviewed current ownership function.
Before dispatch, all inference leases were released and eight tracked monitors idle.

The timeout worker's useful partial identified Lemonade global_timeout. Independently
confirmed live via `lemonade config`: 600 seconds. CLI config uses /internal/config
and /internal/set, not /api/v1/config. Upstream configuration documents this as a
positive HTTP/inference/readiness timeout with live updates. Applied the already
authorized timeout correction as `lemonade config set global_timeout=86400` and
verified readback; appended runtime audit record. This is a finite interim 24-hour
bringup mitigation, NOT indefinite waiting and NOT proof every transport timeout is
gone. No service/model/system restart occurred. Configuration persistence at the
existing loader seam and its implications are assigned to a separate worker.

Eight new packets at clean base 4eb0486, isolated worktrees, freshly generated briefs:
terminal-error exit propagation; parent reservation locking; proxy handler count;
timeout persistence; obsolete executor cfg fixture; pure P1 candidate binding;
single H1 definition validator; read-only contact projection review. Each packet
names exact scope, tests, one deliverable and a 25-minute active-work stopping
budget. The commissioning launcher still has a broader 24-hour process deadline;
the per-packet active-work budget is prompted, not mechanically enforced. Do not
claim otherwise. No timesharing/knowledge-system implementation was dispatched.

All eight were observed running and attachable through reused monitor slots.
Prompts, JSONL and exact session commands are in the ignored commissioning ledger;
`active-batch-aster.md` contains this batch's attach commands. Audit/review and
targeted tests precede integration. Handler-count activation will require a targeted
proxy restart after safe drain; no full CointOS reboot is justified by these packets.

References: https://github.com/lemonade-sdk/lemonade/blob/main/docs/guide/configuration/README.md
and https://github.com/lemonade-sdk/lemonade/blob/main/docs/dev/getting-started.md

## Updated dispatch preference and AFK handoff

David subsequently requested concurrency based on genuinely independent concerns,
usually 1–3 local Qwens, rather than filling eight slots for utilization's sake.
This supersedes the earlier maximize-parallel-Qwen dispatch preference; eight is
capacity, not a target. Leave the current batch undisturbed and apply the preference
to subsequent dispatches. Comprehensive personally checked fresh orientation briefs
are required; the quarantined repository guidance is indexed under `.knowledge/`.

David is heading out and requested a one-hour wait, then artifact inspection and
next bounded dispatches. Aster began the wait around 07:42 UTC on 2026-09-08;
review is due around 08:42 UTC (18:42 Sydney). Use the existing approved reusable
AFK monitor pool, not additional ad-hoc windows. Audit actual patches and outcomes
before acceptance; do not infer success from worker exit alone.

One-hour inspection completed around 08:43 UTC: all eight job records still say
running; all eight worktrees remain clean at 4eb0486, with no implementation
commits. Their JSONL tails contain tool reads/intermediate steps, not final
deliverables; OpenCode server/client processes remain present. No completed packet
was available to accept. No new dispatch or proxy restart was performed: adding
workers would contradict the requested reduction in concurrency. Let this batch
drain, then prioritize terminal-error exit propagation and parent reservation
locking, with independent tests/review before integration. The current batch's
continued orientation and 30–52k-token reported contexts reinforce the need for
the newly required fresh briefs and smaller concurrency; these observations alone
do not measure GPU bottleneck attribution or prove active-work budget compliance.

Subsequent completion: local-contact-projection-review2 emitted a final report and
step_finish reason=stop, with its worktree unchanged. Aster independently reran
tests.test_conversation_projection and tests.test_conversation: 6/6 pass. Confirmed
conversation._projected_row stamps sender=user_id on assistant rows as well as
user rows; existing test checks sender only for the user row. Record a bounded
follow-up to settle the sender contract and add assistant-row coverage before
changing its representation; the reviewer's suggested None is not an accepted
identity design. Its separate lifecycle-linkage concern remains unproven, not
waived because a test pins current behavior. At inspection the durable job still
said running despite the final packet, so semantic completion is established but
lease/process cleanup has not been verified. No replacement worker dispatched.
