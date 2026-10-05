---
status: green
revised_at: "2026-10-05T21:32:08+11:00"
---

## Every finished reply re-reads its own tokens

The work model runs MTP speculative decoding. When a reply ends, the server has already evaluated draft tokens past end-of-turn (`tokens_cached` exceeds the known tokens), and hybrid state cannot be cut back, so `backend_llama.think` correctly reports the lane as holding nothing. The task's next request restores its prompt-end checkpoint and re-reads the reply plus the tool output. The server reads prompts at about 119 tokens/s and generates about 700k tokens a day, so re-reading replies costs at most about 1.6 GPU-hours a day (roughly 7%); the tool output read alongside it is necessary work.

The cost is accepted for now. The user has declined to patch llama.cpp (retaining no draft tokens beyond an end-of-generation token) at this time; disabling drafting would remove the cost only at a large generation-speed loss.

## A conversation sometimes diverges right after the agent sends a message

Unexplained. Agents exchanging messages normally restore their whole context from cache (two agents messaging each other all evening restored 28k–31k of 28k–31k tokens on most switches). But on 2026-10-05 three divergences followed immediately after the agent's own `cointos_send`: two sends to `user` at 20:09:38 and 20:13:22 (then `snapshot forgotten … diverged` and `restored 0`) and one send to a peer at 20:18:32 (partial reread). `forget_diverged` drops a task's snapshots that do not begin the context its next request renders, so the rendered history before the snapshot's end changed. The mechanism is not established; candidates are how OpenCode records that tool call or its result, and whether a delivered `noReply` message interleaves with the in-progress assistant message. Next check: compare the rendered prompts before and after such a send (the `divergence` journal event only fires when the lane still holds the same owner).

## Silent snapshot eviction hid lost contexts

When a snapshot tier is full, `snapshots.disk_room` and `snapshots.evict` drop the least recently run snapshots; until 2026-10-05 this logged nothing. With the disk tier capped at 100 GB and holding about 79 GB of 57 snapshots, rotation spills evicted waiting agents' contexts, causing full rereads (80k tokens for one manager) with no explanation in the journal. The disk tier is now 300 GB, RAM 40 GB, and every eviction logs `snapshot evicted` with owner, tier and tokens. `snapshots.room` still declines a save rather than overcommitting RAM while spills are in flight (`tests/test_snapshot_limit.py`); not known to have fired.
