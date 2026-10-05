---
status: green
revised_at: "2026-10-05T21:52:29+11:00"
---

## Every finished reply re-reads its own tokens

The work model runs MTP speculative decoding. When a reply ends, the server has already evaluated draft tokens past end-of-turn, and hybrid state cannot be cut back, so `backend_llama.think` reports the lane as holding nothing. The next request restores its prompt-end checkpoint and re-reads the reply plus the tool output: at most about 1.6 GPU-hours a day (roughly 7%). Accepted for now; the user has declined to patch llama.cpp, and disabling drafting costs far more generation speed.

Similarly, a snapshot saved mid-generation often stops matching when OpenCode replays the reply: the template trims whitespace generated before `</think>`, or the text retokenizes differently. The `divergence` journal event shows both sides; the checkpoint survives, so only that reply is re-read.

## Two agents lost their whole context right after messaging the user

Unexplained. On 2026-10-05 at 20:09:39 and 20:13:22, the request after a `cointos_send` to `user` forgot the task's prompt-end checkpoint too and read about 29k tokens cold, although the prompt had grown by about 155 tokens; something before the checkpoint changed. Ruled out: the pinned system prompt (same digest), OpenCode pruning (off unless `compaction.prune`), auto-compaction (overflow only), the Qwen template (appended user messages keep the earlier rendering as a prefix, checked live), and mid-loop rewording of user messages (absent from OpenCode 1.18.34). Tools were not pinned then, and `mcp.catalogue` filters by a role fetched from the daemon per `tools/list`, dropping role tools when the daemon is unreachable; tool pinning now neutralizes that path. Next check: reconstruct both requests from OpenCode's stored session (`~/.local/share/opencode/opencode.db`, `ses_ef4f30304ffebuuMoBH47DXVKm`) and diff their renderings.

## Silent snapshot eviction hid lost contexts

Full snapshot tiers drop least recently run snapshots (`snapshots.disk_room`, `snapshots.evict`). Until 2026-10-05 this logged nothing, and a 100 GB disk cap evicted waiting agents' contexts. The disk tier is now 300 GB, RAM 40 GB, and every eviction logs `snapshot evicted` with owner, tier and tokens. `snapshots.room` still declines a save rather than overcommitting RAM while spills are in flight; not known to have fired.
