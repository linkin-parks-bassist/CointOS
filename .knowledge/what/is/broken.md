---
status: green
revised_at: "2026-10-06T20:44:44+11:00"
---

## Pigen's lowering tests cannot yet be run per behavior

Landings now require an item's own tests (its brief's `Tests:` commands) to pass, but Pigen's `tests/contracts.json` still maps all lowering code to the one whole-binary command `make rtl-lower-test`, and all Task 8 assertions sit in one section, `t8-skeleton`. Until Pigen registers one entry per section and splits that section by behavior, no Task 8 implementation can name its own tests, and the whole-binary entry, red on main, protects no other lowering section against regression. The Pigen manager command `split-rtl-lower-tests-per-behavior` owns that correction; `impl-t8-fire-identity-bits-fix` and its integration are held for it (its branch passes the fire-identity family).

## Every finished reply re-reads its own tokens

MTP speculative decoding evaluates draft tokens past end-of-turn, and hybrid state cannot be cut back, so `backend_llama.think` reports the lane holding nothing; the next request restores its prompt-end checkpoint and re-reads the reply plus tool output: at most about 1.6 GPU-hours a day (roughly 7%). Accepted; the user declined to patch llama.cpp, and disabling drafting costs far more speed.

A snapshot saved mid-generation often stops matching when OpenCode replays the reply (trimmed whitespace before `</think>`, retokenized text, or a reply cut by a live installation replayed as two steps); `divergence` shows both sides and only that reply is re-read. A lost checkpoint logs `prompt rewritten` with both texts.

Near its 131,072-token window (about 114k), OpenCode compacts a conversation: the summarising request has no tool list and truncated tool output, so it is read cold once (about 41k tokens, roughly 6 minutes). Accepted.

## Two agents lost their whole context right after messaging the user

Unexplained. On 2026-10-05 at 20:09:39 and 20:13:22, the request after a `cointos_send` to `user` lost its checkpoint and read about 29k tokens cold, though the prompt grew about 155 tokens. Ruled out: the pinned system prompt, OpenCode pruning/compaction, the Qwen template and mid-loop rewording. Tools were not then pinned, and `mcp.catalogue` drops role tools when its ledger lookup fails; pinning now neutralizes that. A later send (22:14:05) kept its checkpoint. If it recurs, `prompt rewritten` names the cause.

## Silent snapshot eviction hid lost contexts

Full tiers drop snapshots (`snapshots.disk_room`, `snapshots.evict`), shared launch starts first. A 100 GB disk cap once silently evicted waiting agents' contexts; the disk tier is now 300 GB, RAM 40 GB, and each eviction logs `snapshot evicted` with owner, tier and tokens. `snapshots.room` still declines a save rather than overcommitting RAM during spills; not known to have fired.
