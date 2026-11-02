---
status: green
revised_at: "2026-11-03T00:27:25+11:00"
---

Coin reread because two defects combined. Both repairs are installed and a live pair of wakes confirmed them with no agents running: a turn after a prompt change read all 19,628 tokens and took 61 seconds to its first words, three rounds then ran at generation speed with no lane switch, and the next wake restored 15,860 of 18,379 tokens in 0.78 seconds and finished in 12 seconds. Changing Coin's prompt or tools still costs one full read on its next turn. A wake's first response also includes up to 384 tokens of reasoning, about 24 seconds. Preempting a running agent has not been timed.

**Requests diverged from Coin's resident state.** `coin.complete` appended a `<cointos-message-times>` user message as each request's tail without retaining it, and Coin dropped generated reasoning, so the next request differed at that position (for example held 15,075, next 16,788, common 14,104). Gufo resident state cannot truncate, so `lanes.switch` needed a compatible snapshot. The block is present from c999367 (2026-10-24), and restored shares were already partial on 2026-10-22, when the event logs begin.

The repair keeps timestamps beside the clock in Coin's retained transcript (`coin.message_times`), echoes `reasoning_content`, and gives Coin the same `tool_history` token reuse as task agents under one `gateway.COIN_HISTORY` owner. The record's conversation digest binds it to one transcript. Inserting a changed context block mid-turn still falls back to a snapshot, and a later turn rebuilds from archived text, so it restores Coin's retained prefix and reads the rest.

**Snapshots could not be saved while three agents ran.** `snapshots.keep` needs the estimated file plus `resident_state_bytes` (11.35 GB), installed 2026-10-27, and `capacity.headroom_gb()` also subtracts 8.59 GB per agent. One three-agent sample: 24.4 - 25.77 = -1.37 GB, leaving nothing to evict. The refusal was silent, so it is inferred from arithmetic and timing: on 2026-11-02 the newest file was written 25 seconds after the third agent started, and Coin restored 0 tokens until an agent ended, when it restored 13,194 of 15,604.

The repair exempts Coin's conversation, its resident state and the shared starts its requests save from process-cap claims through `capacity.conversation_cache_gb`. Other claims and the reserve still apply. Worst case, three agents reaching their caps during a capture dip into the 24 GB reserve until the guard sheds caches. `snapshot refused` events now record refusals.

Coin's daily requests, zero-restore requests and restored share before the repair: 2026-10-22 to 10-29, 565, 29, 51-73%; 10-30, 93, 70, 15%; 10-31, 7, 7, 0%; 11-01, 7, 3, 44%. Whether admission caused the 10-30 to 11-01 clusters is unverified.

Evidence: tests test_capacity, test_coin_history and test_tool_history.
