---
status: green
revised_at: "2026-10-16T02:35:36+11:00"
---

MTP state beyond returned tokens is cold; the next request rereads reply/tool output. Native token-limit/word-stop fixtures retain cache, so not every terminal reply suffers. Matched 77k stock/patched trials overlap in decode speed; live throughput gains remain unproved. The benchmark owner owns those comparisons.

Reply retokenization, whitespace and interrupted output can invalidate mid-generation snapshots. Recovery should use the longest compatible committed checkpoint. Long-prompt checkpoints leave 32 tail tokens; a native version edit restored 4,438/4,471 tokens in 1.54 seconds. Larger divergence can still read cold.

A native resumed worker exposed a separate checkpoint omission: its reasoning allowance was already exhausted, so reasoning_step inserted three closing tokens before prefill. lanes.worker treated a nonempty generated buffer as evidence that prompt checkpointing was over. No committed prompt checkpoint survived; the next tool transcript changed at token 51,732 after a 51,729-token prompt and restored zero tokens despite that entire original prompt still matching. This is a phase-accounting defect, not necessary rereading.

Installed code schedules the committed checkpoint by native held position within the prompt, independently of synthetic output tokens. A regression reproduces the missing checkpoint before the fix and restores 2,967 of 3,000 prompt tokens after a changed tool-message tail afterward. Installed scheduler/reasoning/snapshot replay passes 82 tests. After compatible deployment, a native operator's changed tool-message tail restored 61,948 of 62,734 tokens. This establishes observed native fallback reuse; the focused regression specifically covers the exhausted-reasoning trigger.

Near the 131,072-token window, OpenCode compacts through a tool-free request with truncated tool output. That deliberately changed context requires a cold read; normal compaction remains accepted.

Source regression for exhausted continuation and committed-prefix reuse:

Proof:

```bash
cd "$(git rev-parse --show-toplevel)" && python3 -m unittest -q tests.test_turns.Turns.test_exhausted_reasoning_continuation_keeps_the_prompt_before_tool_retokenization tests.test_reasoning_budget
```
