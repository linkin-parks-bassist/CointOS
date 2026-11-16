---
status: green
revised_at: "2026-11-08T16:03:40+11:00"
---

By the user's direction, the knowledge tree is the general-purpose memory; there is no separate notebook. Coin should write nearly everything down, in the tree it belongs to. `~/.knowledge` is the home-computer tree, which Coin looks after and reads first, and its actor can write there, where kt calls it `local`. `~/.CointOS/.knowledge` is only for how CointOS works and its state. Project facts go in project trees, and private or professional details go only in their own trees; `where/am/i.md` names those, because source intended for publication must not.

`coin.orientation` runs `kt info --no-prove` from home once per process and appends it to Coin's system prompt, so `where/am/i.md` and the dictionary are in context at every start and the prompt prefix stays fixed until a restart. It adds about 25 KB. Before this, Coin's prompt had no kt startup output at all. `where/am/i.md` carries the general lay of the land, so a failed exact-word lookup does not lead to searching the whole home.

The motivating failure: Coin looked up "training log" while the leaf said workouts. kt lookup matches words lexically, so it concluded the tree had no answer and scanned home. Its role now says a miss usually means the wrong word, names leaves as short plain questions about one thing, and says to dispatch an Operator or gardener for more than a quick note. The user rejected hardcoded tool refusals as the way to stop this. Limits remain: `fs_search` stops after 30 seconds and skips generated trees, and `run_command` defaults to 300 seconds.

Coin keeps `coin.history_messages` (50) of conversation text, dropping `coin.history_trim_messages` (20) on rollover. History holds no tool calls or results, which is why findings must be written to a tree.

Dispatched agents document their own work in the tree that owns it, by the user's decision, rather than sending Coin detailed reports. Coin names that tree in the brief. When tracked work settles, `coin_followups.observe` wakes Coin to verify and report it and to see that its own tree still leads to the work.

`cointos log TASK`, or `cointos log coin`, reads a record as a numbered index, filtered by `--kind`, `--turn` and `--grep`, with `--show N-M` for full entries. Source also exposes assignment records to managers, integrators, Operators, Stewards and test auditors through the daemon. Coin's conversation remains restricted to Supervisors and First Responders; workers may inspect only their own trace. Dispatch's logs ability grants tool visibility, not broader conversation authority. how/do/cointos/coordinators/inspect/task/records/and/source.md owns private-store selection and inspection boundaries.
