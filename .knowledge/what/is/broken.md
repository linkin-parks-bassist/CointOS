---
status: green
revised_at: "2026-10-05T20:55:30+11:00"
---

## Every finished reply re-reads its own tokens

The work model runs MTP speculative decoding. When a reply ends, the server has already evaluated draft tokens past end-of-turn (`tokens_cached` exceeds the known tokens), and hybrid state cannot be cut back, so `backend_llama.think` correctly reports the lane as holding nothing. The task's next request restores its prompt-end checkpoint and re-reads the reply plus the tool output. The server reads prompts at about 119 tokens/s and generates about 700k tokens a day, so re-reading replies costs at most about 1.6 GPU-hours a day (roughly 7%); the tool output read alongside it is necessary work. Before the labelling fix, `switch` events reported these empty-lane restores as `diverged`.

The cost is accepted for now. The user has declined to patch llama.cpp (retaining no draft tokens beyond an end-of-generation token) at this time; disabling drafting would remove the cost only at a large generation-speed loss. A `divergence` event logs the exact split text whenever a lane that held state truly diverges.

## A full RAM snapshot tier skips saving the outgoing context

`snapshots.room` does not credit RAM until an in-flight spill to disk finishes, so when the RAM snapshot budget is full a lane switch declines to save the outgoing agent's context (`switch` event `saved: false`), and that agent re-reads its whole conversation on its next turn. With four agents rotating on one lane and a 24 GB budget this caused repeated 30k–80k-token prefills that stalled the workstation. The budget is now 40 GB (`memory.snapshots_gb`, disk tier `memory.disk_snapshots_gb` 300), which fits four agents' contexts, so normal rotation should not trigger it. The structural fix, crediting in-flight spills or evicting older snapshots instead of declining the newest, conflicts with the deliberate no-overcommit tests in `tests/test_snapshot_limit.py` and is unresolved. Next check: `switch` events with `saved: false` followed by `restored: 0` for the same owner.
