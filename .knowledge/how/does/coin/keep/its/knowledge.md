---
status: green
revised_at: "2026-11-03T07:59:07+11:00"
---

By the user's direction, the knowledge tree is the general-purpose memory; there is no separate notebook. `~/.knowledge` is the home-computer tree that Coin should read and write often, and `~/.CointOS/.knowledge` is only for how CointOS works and its state. Coin's actor can write `~/.knowledge`, where kt calls it `local`.

`coin.orientation` runs `kt info --no-prove` from home once per process and appends it to Coin's system prompt, so `where/am/i.md` and the dictionary are in context at every start and the prompt prefix stays fixed until a restart. It adds about 25 KB. `where/am/i.md` carries the general lay of the land, such as where personal documents are kept, so a failed exact-word lookup does not lead to searching the whole home.

The motivating failure: Coin looked up "training log" while the leaf said workouts. kt lookup matches words lexically, so it concluded the tree had no answer and scanned home. Its role now says a miss usually means the wrong word, names leaves as short plain questions about one thing, and says to dispatch an Operator for more than a quick note. The user rejected hardcoded tool refusals as the way to stop this. Limits remain: `fs_search` stops after 30 seconds and skips generated trees, and `run_command` defaults to 300 seconds.

Coin keeps `coin.history_messages` (50) of conversation text, dropping `coin.history_trim_messages` (20) on rollover. History holds no tool calls or results, which is why findings must be written to the tree. When tracked work settles, `coin_followups.observe` wakes Coin with the agents' receipts, capped at 8,000 characters, and asks it to see that `~/.knowledge` records what changed.

`cointos log TASK`, or `cointos log coin`, reads a record as a numbered index, filtered by `--kind`, `--turn` and `--grep`, with `--show N-M` for full entries. Supervisors and First Responders have it as the `log` MCP tool; dispatch's `logs` ability grants that tool to any role, and the command itself works from any shell.
