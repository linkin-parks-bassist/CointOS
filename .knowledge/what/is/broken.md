---
status: green
revised_at: "2026-10-05T21:25:02+11:00"
---

## Every finished reply re-reads its own tokens

The work model runs MTP speculative decoding. When a reply ends, the server has already evaluated draft tokens past end-of-turn (`tokens_cached` exceeds the known tokens), and hybrid state cannot be cut back, so `backend_llama.think` correctly reports the lane as holding nothing. The task's next request restores its prompt-end checkpoint and re-reads the reply plus the tool output. The server reads prompts at about 119 tokens/s and generates about 700k tokens a day, so re-reading replies costs at most about 1.6 GPU-hours a day (roughly 7%); the tool output read alongside it is necessary work.

The cost is accepted for now. The user has declined to patch llama.cpp (retaining no draft tokens beyond an end-of-generation token) at this time; disabling drafting would remove the cost only at a large generation-speed loss.

## A message arriving mid-turn invalidates the recipient's cache

`messages.pending` posts a `noReply` user message into the recipient's session as soon as it has a live session. OpenCode orders messages by creation, so a message posted while the agent's reply is still in progress sits before that reply's later steps, and Qwen's chat template strips reasoning from assistant messages that precede a user message. The in-progress turn therefore re-renders differently, and the next request diverges from every saved state past the turn's start (`snapshot forgotten … diverged`, then a partial reread such as 19,181 of 30,032 tokens). Agents that message often reread often. Proposed fix, awaiting the user: deliver messages only when the recipient's current reply has finished.

## Silent snapshot eviction hid lost contexts

When a snapshot tier is full, `snapshots.disk_room` and `snapshots.evict` drop the least recently run snapshots; until 2026-10-05 this logged nothing. With the disk tier capped at 100 GB and holding about 79 GB of 57 snapshots, rotation spills evicted waiting agents' contexts, causing full rereads (80k tokens for one manager) with no explanation in the journal. The disk tier is now 300 GB, RAM 40 GB, and every eviction logs `snapshot evicted` with owner, tier and tokens. `snapshots.room` still declines a save rather than overcommitting RAM while spills are in flight (`tests/test_snapshot_limit.py`); not known to have fired.
