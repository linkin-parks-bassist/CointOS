---
status: green
revised_at: "2026-10-10T16:58:17+11:00"
---

## Coin misses the 15-second reply target

Coin runs on the work model alone. Proof of life meets 15 seconds only with the lane free and its shared start restored; cold reads and pre-emption take 23–30 seconds, tool-using turns minutes, and only `status` answers while the guard has the work model unloaded (measurements in `how/does/telegram/reach/cointos.md`). Proof-of-life compliance with the per-message reminder rests on one live turn. Coin has no tool to answer an agent that messaged the user.

## The memory guard can unload the work model its own reload just loaded

Loading the work model alone drives PSI `full avg10` to about 6 and keeps it above `memory.max_psi` for about 21 seconds, even with 83 GB available (measured 2026-10-07). `daemon.guard` treats PSI above the limit for `memory.distress_seconds` as urgent and unloads the model. Shedding under genuine desktop load is correct. The defect is the reload: its own spike plus leftover desktop pressure can outlast the window, so the guard unloads the model it just loaded and repeats, each reload stalling the desktop for about 20 seconds. Seen only under a busy desktop. Proposed, awaiting the user: unload only when headroom stays negative after snapshots and background agents give way.

## Implementers can find their hidden test packets

Accepted test-packet commits stay in the project repository (archived under `refs/cointos/archive/`), so `git log --all` or `git show` reaches them. The first live implementer, `pigen:impl-t8-fire-identity-bits-fix`, found its packet by the test item's name and applied its tests to its own worktree. The worker prompt forbids this and the landing gate rejects implementation commits that touch tests, but nothing mechanical hides the tests. Proposed, awaiting the user: move accepted packet commits into a CointOS-owned repository and fetch them only for the packet check and the integrator's review.

## Concurrent test runs can share Pigen build outputs

Pigen's test targets build fixed paths such as `/tmp/pigen-rtl-lower-test`, so a packet check running while a landing checks the same target could overwrite the other's binary. Landings are serialized per repository, but packet checks are not serialized against them. Not yet seen.

## Every finished reply re-reads its own tokens

MTP speculative decoding evaluates draft tokens past end-of-turn, and hybrid state cannot be cut back, so `backend_llama.think` reports the lane holding nothing; the next request restores its prompt-end checkpoint and re-reads the reply plus tool output: at most about 1.6 GPU-hours a day (roughly 7%). Accepted; the user declined to patch llama.cpp, and disabling drafting costs far more speed.

A snapshot saved mid-generation often stops matching when OpenCode replays the reply (trimmed whitespace before `</think>`, retokenized text, or a reply cut by a live installation); `divergence` shows both sides and only that reply is re-read. A lost checkpoint logs `prompt rewritten` with both texts.

Near its 131,072-token window (about 114k), OpenCode compacts a conversation: the summarising request has no tool list and truncated tool output, so it is read cold once (about 41k tokens, roughly 6 minutes). Accepted.

## Two agents lost their whole context right after messaging the user

Unexplained. On 2026-10-05, two requests after a `cointos_send` to `user` lost their checkpoints and read about 29k tokens cold, though each prompt grew only about 155 tokens. Ruled out: the pinned system prompt, OpenCode pruning/compaction, the Qwen template and mid-loop rewording. `mcp.catalogue` dropped role tools when its ledger lookup failed; tool pinning now neutralizes that. If it recurs, `prompt rewritten` names the cause.

## Silent snapshot eviction hid lost contexts

Full tiers drop snapshots (`snapshots.disk_room`, `snapshots.evict`), shared launch starts first; the disk tier is 300 GB, RAM 40 GB, and each eviction logs `snapshot evicted` with owner, tier and tokens. `snapshots.room` still declines a save rather than overcommitting RAM during spills; not known to have fired.
