---
status: green
revised_at: "2026-10-05T23:34:29+11:00"
---

## Every finished reply re-reads its own tokens

The work model runs MTP speculative decoding. When a reply ends, the server has already evaluated draft tokens past end-of-turn, and hybrid state cannot be cut back, so `backend_llama.think` reports the lane as holding nothing. The next request restores its prompt-end checkpoint and re-reads the reply plus the tool output: at most about 1.6 GPU-hours a day (roughly 7%). Accepted for now; the user has declined to patch llama.cpp, and disabling drafting costs far more generation speed.

Similarly, a snapshot saved mid-generation often stops matching when OpenCode replays the reply (whitespace before `</think>` trimmed, text retokenized, or a reply cut by a live installation replayed as two steps); the `divergence` journal event shows both sides, and the checkpoint survives, so only that reply is re-read. Losing the checkpoint itself is logged as `prompt rewritten` with the text on both sides.

When a conversation nears its 131,072-token window (about 114k), OpenCode compacts it: the summarising request has no tool list and truncated tool output, so it is read cold once (about 41k tokens, roughly 6 minutes), after which the conversation continues warm. Accepted as the cost of a full context.

## Two agents lost their whole context right after messaging the user

Unexplained. On 2026-10-05 at 20:09:39 and 20:13:22, the request after a `cointos_send` to `user` lost the prompt-end checkpoint and read about 29k tokens cold, though the prompt grew by about 155 tokens. Ruled out: the pinned system prompt (same digest), OpenCode pruning and compaction, the Qwen template (checked live) and mid-loop rewording of user messages. Tools were not pinned then, and `mcp.catalogue` drops role tools when its per-`tools/list` ledger lookup fails; pinning now neutralizes that path. A later send to `user` (22:14:05) kept its checkpoint. If it recurs, the `prompt rewritten` event names the cause.

## Silent snapshot eviction hid lost contexts

Full snapshot tiers drop snapshots (`snapshots.disk_room`, `snapshots.evict`), shared launch starts first. Until 2026-10-05 this logged nothing, and a 100 GB disk cap evicted waiting agents' contexts. The disk tier is now 300 GB, RAM 40 GB, and every eviction logs `snapshot evicted` with owner, tier and tokens. `snapshots.room` still declines a save rather than overcommitting RAM while spills are in flight; not known to have fired.
