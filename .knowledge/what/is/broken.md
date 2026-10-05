---
status: green
revised_at: "2026-10-05T21:06:56+11:00"
---

## Every finished reply re-reads its own tokens

The work model runs MTP speculative decoding. When a reply ends, the server has already evaluated draft tokens past end-of-turn (`tokens_cached` exceeds the known tokens), and hybrid state cannot be cut back, so `backend_llama.think` correctly reports the lane as holding nothing. The task's next request restores its prompt-end checkpoint and re-reads the reply plus the tool output. The server reads prompts at about 119 tokens/s and generates about 700k tokens a day, so re-reading replies costs at most about 1.6 GPU-hours a day (roughly 7%); the tool output read alongside it is necessary work. Before the labelling fix, `switch` events reported these empty-lane restores as `diverged`.

The cost is accepted for now. The user has declined to patch llama.cpp (retaining no draft tokens beyond an end-of-generation token) at this time; disabling drafting would remove the cost only at a large generation-speed loss. A `divergence` event logs the exact split text whenever a lane that held state truly diverges.

## A full RAM snapshot tier would decline the newest save

`snapshots.room` does not credit RAM until an in-flight spill to disk finishes, so when the RAM snapshot budget is full, saving the outgoing context on a lane switch is declined rather than overcommitting RAM, and that agent rereads its conversation on its next turn. Evicting older snapshots instead conflicts with the deliberate no-overcommit tests in `tests/test_snapshot_limit.py`; unresolved. With `memory.snapshots_gb` 40 and four agents the tier sat far from full (about 10 GB), so this is not known to have fired; a `switch` event's `saved: false` alone usually means the lane held nothing worth saving. The 2026-10-05 prefill storms were instead caused by relaunched sessions loading changed tool schemas, which invalidated every saved context; tool definitions are now pinned per task (`gateway.stable_tools`). Next check: a `saved: false` switch followed by `restored: 0` for the same owner with no `snapshot forgotten` event between.
