---
status: green
revised_at: "2026-10-04T19:17:14+11:00"
---

## Every finished reply re-reads its own tokens

The work model runs MTP speculative decoding. When a reply ends, the server has already evaluated draft tokens past end-of-turn (`tokens_cached` exceeds the known tokens), and hybrid state cannot be cut back, so `backend_llama.think` correctly reports the lane as holding nothing. The task's next request restores its prompt-end checkpoint and re-reads the reply plus the tool output. The server reads prompts at about 119 tokens/s and generates about 700k tokens a day, so re-reading replies costs at most about 1.6 GPU-hours a day (roughly 7%); the tool output read alongside it is necessary work. Before the labelling fix, `switch` events reported these empty-lane restores as `diverged`.

Candidate remedies: patch llama.cpp so a speculative step retains no draft tokens beyond an end-of-generation token (removes the cost, adds a local patch to Lemonade's server), or disable drafting (removes the cost at a large generation-speed loss). Undecided by the user. A `divergence` event now logs the exact split text whenever a lane that held state truly diverges.
