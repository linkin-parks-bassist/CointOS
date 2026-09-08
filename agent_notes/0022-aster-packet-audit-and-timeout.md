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
