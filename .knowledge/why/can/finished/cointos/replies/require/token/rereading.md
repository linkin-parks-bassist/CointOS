---
status: green
revised_at: "2026-11-16T13:28:54+11:00"
---

A reread is needed when the next rendered tokens do not extend the held state and no compatible checkpoint can be restored. Reply retokenization, whitespace, interrupted output and deliberate compaction can change a prefix. Unreachable-cache cleanup can also discard state; these causes require separate metadata evidence.

Gufo resident state retains the published token vector and can continue from equality or extension. Older buffered MTP paths could have cold state beyond returned tokens; native token-limit/word-stop fixtures retain cache, so not every terminal reply suffers. Matched 77k stock/patched trials overlap in decode speed; the benchmark owner retains their limits.

Recovery uses the longest compatible committed checkpoint. Long-prompt checkpoints leave 32 tail tokens; a native version edit restored 4,438/4,471 tokens in 1.54 seconds. Larger divergence or insufficient checkpoint headroom can still read cold. Private user mode must preserve this normal fallback: its owner-bound checkpoints are binary KV in tmpfs, not transcript logs, and cannot spill to disk. Disabling all private checkpoints left only the latest resident state, which cannot rewind a changed tail. The private regression restores 2,967/3,000 tokens after a tail change. Private divergence diagnostics report lengths/common-prefix position without decoding text.

A separate native resumed worker had an exhausted reasoning allowance, so reasoning_step inserted three closing tokens before prefill. The old worker treated a nonempty generated buffer as proof prompt checkpointing had ended. A changed tool transcript then restored zero despite its 51,729-token original prompt matching. Current code schedules the committed checkpoint by native held position within the prompt, independently of synthetic output. The regression restores 2,967/3,000 tokens; a native operator's changed tail restored 61,948/62,734. These establish scoped fallback reuse, not universal cache retention.

Near the 131,072-token window, OpenCode compacts through a tool-free request with truncated tool output. That deliberately changed context requires a cold read; normal compaction remains accepted.

Proof:

```bash
cd "$(git rev-parse --show-toplevel)" && python3 -m unittest -q tests.test_turns.Turns.test_exhausted_reasoning_continuation_keeps_the_prompt_before_tool_retokenization tests.test_turns.Turns.test_private_user_reuses_ram_checkpoint_after_a_message_changes_the_tail tests.test_reasoning_budget
```
