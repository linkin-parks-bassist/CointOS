---
status: green
revised_at: "2026-10-19T06:21:08+11:00"
---

Within one class, lane time is shared by a weighted lottery. Class pre-emption is strict within eligible same-model lanes: Coin outranks user sessions, then background agents. Separate engines can contend on the shared GPU; MiniCPM/Qwen probes exposed this gap. MiniCPM is now unloaded and Coin shares construction's Qwen lane, so existing priority applies. No cross-engine priority change is deployed.

**Slice clock.** Reading and generation count from turn admission; completing an opening read does not restart the clock. Quick tool follow-ups continue the same unexpired turn.

**Partial reads.** At a completed read boundary after the slice expires, the worker asks whether an equal would win. Only then does it attempt a suspended snapshot of the exact prepared prefix. A saved same-model checkpoint with the current held length permits the reader to enter the draw. Missing, moving, discarded or mismatched checkpoints keep it protected. Failed admission or an ordinary save error preserves successful reading; native state loss invokes recovery. No backend step is interrupted. Later eviction can still cause rereading.

**Tail checkpoint.** Long prompts save the committed checkpoint 32 tokens before the prepared prompt end; short prompts retain the old end. Reading still reaches one token short before generation. A warm prefix beyond the preferred boundary advances once and freezes that position. Worker tests show a 16-token tail edit restores the earlier 2,967-token checkpoint and prepares only 32 tokens, with one saved state; warm near-end input also saves once. Native /tmp/cointos-native-tail-reuse-evidence.json verifies a 4,471-token version edit restores 4,438 tokens and prepares 32: 1.54s versus the first cold request's 36.37s. This is cache reuse, not decode-rate evidence. Sustained workload benefit remains to measure.

**Diagnose waiting.** Reading and zero newly-read tokens do not establish a cold read: inspect restored prefix and unread suffix. Passive native /metrics deltas separate prompt and generation work without submitting requests. One 35.17-second observation processed 3,070 prompt tokens in 25.9 seconds and no generation; the manager's GPU counter increased by 26.0 seconds. gpu_seconds minus generation_seconds also includes transfers/overhead, and time outside the GPU mixes waits with tools. Attribute latency from step/wait evidence.

**Draw.** Global slots are now // slice_seconds. Each agent's seeded lot is u^(1/weight); highest wins with probability proportional to weight. Lots are stable within a slot and redrawn next slot. An expired holder winning again avoids switching. Placement prefers own/kept, warm and free lanes, then generating holders before readers and lower winning lots.

**Weights.** Worker/integrator weight is 4; manager weight is 2. Installed Operators receive weight 2 for primary recovery; active native thoughts confirm it. The fallback weight 1 remains for unlisted roles and taskless thoughts. The native recovery Operator's repeated long waits while workers/reviewers progressed exposed the inappropriate inherited fallback. This adjustment changes expected service share, not the lottery's unbounded waiting tail.

An actual-draw 10,000-choice experiment with three weight-4 workers and one weight-1 helper has helper missed-choice p95/p99/max of 40/60/83. Accounting candidates keep the 1/13 share and reduce these to 12, but increase switches. These are slot experiments, not native latency/throughput; /tmp/cointos-scheduler-experiment-20261012/report.md owns the comparison. Production assignment matches the slot oracle in 10,000 represented boundary cases. Accounting remains uninstalled pending lane/clock/grace/read/restart and transfer-cost verification.

**Checks.** Starvation means a winning waiting equal remains unapplied beyond checks.preempt_seconds after the latest of arrival, slice end and slot start. Checkpointed readers are eligible; unsaved readers are excluded. Scheduler/health tests cover lottery and protection. Worker tests exercise partial save, peer reply and restoration, plus refusal/errors/unavailable checkpoints. Live resumes preserve prefixes across peer work. Rewritten compaction prompts and new tool-result tails cause additional reading; restored-token counts identify the unread suffix. Transfer costs and useful-throughput gains remain unproved.

Proof:

```bash
cd "$(git rev-parse --show-toplevel)" && python3 -m unittest -q tests.test_scheduler tests.test_memory_and_checks tests.test_turns
```
