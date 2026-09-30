---
status: green
revised_at: "2026-10-01T06:51:39+10:00"
---

Full autonomous acceptance is not established. Source mechanism tests pass; those prove mechanisms, not every live scenario.

## Proven live boundary

- **Receipt replay:** the live daemon returned the exact stored receipt twice for completed `system:operator-prefix-reuse-2-1`, including its original timestamp and evidence; a fabricated stale run was refused and the full task remained unchanged. This proves retry after a lost completion reply and stale rejection against a terminal task. Stale rejection against a newer active run remains unproved.
- **Receipt lifecycle:** workers, integrators, managers, gardeners, tree auditors, stewards and test auditors have completed through checked receipts. Terminal commands flush and acknowledge the exact receipt before their managed unit is retired. Final text, transport finish markers and process exit do not settle a task. Ordinary completed runs leave no stray units.
- **Directed run control:** `cointos kill AGENT` stops one run, refunds its attempt and durably holds unfinished work with artifacts preserved. Only `cointos resume TASK` releases that hold; `go` does not. A held task's effort can be changed with `cointos reasoning` before release.
- **Restart admission:** ordinary daemon drain closes spawn admission while existing conversations, landing validations and receipts continue. Deployment quiescence lets admitted thoughts finish, retryably blocks new thoughts, and has both a clean cancellation path and a successful replacement path.
- **Compatible live installation:** cointosd has been replaced around exact surviving agent units and session IDs without relaunch or continuation injection. The installer accepts daemon-policy drift, rejects gateway/backend/model identity drift before side effects, and restarts cointosd if a later installation step fails. The replacement daemon can take several seconds to accept API calls after the installer returns.
- **Continuation:** OpenCode 1.18.33 rejects empty noninteractive session resume. The installed fallback persists the minimal real user turn `Continue.` for gaps under three hours and one concise reorientation after longer gaps; live sessions accepted it and continued.
- **Shutdown baseline:** a real reboot proved one daemon start, explicit service PATH, cointosd-before-agent stop ordering, independent shutdown obligations and disk spill. It also exposed the prefix-pinning and dead-unit-adoption defects now repaired in source; their repaired reboot behavior is not yet proved.
- **Reasoning calibration:** live Qwen3.8 agents use per-reply caps of 256/384/1,024 tokens for low/medium/xhigh. The installed runtime defaults test-contract workers and managers to medium and other tasks to low unless explicitly overridden; the manager default was installed live, and a medium manager run's outcome quality is not yet observed.
- **Operator lifecycle and sequential role reuse:** bounded read-only system operators ran with explicit low effort and 180-second/2,000-token generation limits, called the live status/check controls, submitted checked complete receipts, and had their units retired with all nine checks green. After installation, the first operator cold-started at 0 of 21,533 prompt tokens and seeded a 21,147-token shared operator prefix; the next same-role operator restored all 21,147 tokens, reached its first tool call in under 20 seconds and completed seconds later. Prefill does not spend generation budget. CLI-launched lifecycle and proactive same-role prefix reuse are proved; Coin-triggered launch and latency quality are not.
- **Pipeline evidence:** ordinary intake has produced accepted Pigen/Todo work through worker, integration, managerial and retrospective-audit roles. This demonstrates useful flow, not the sustained four-agent/two-lane acceptance scenario.

## Not yet accepted

The current gaps are the focused live paths and whole-system scenarios listed in `what/is/broken.md`: repaired reboot recovery, useful fresh recovery, stale-run rejection against a newer active run, process-death and halt paths, Coin response timing, workstation priority, concurrent integration, snapshot churn and the sustained soak.

`what/is/the/plan.md` owns their execution order. Runtime events and Git own chronology; this leaf records only the present evidence boundary.
