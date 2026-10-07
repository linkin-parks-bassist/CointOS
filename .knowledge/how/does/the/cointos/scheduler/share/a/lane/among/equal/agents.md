---
status: green
revised_at: "2026-10-07T19:26:02+11:00"
---

Within one class (in practice, among `background` agents), lane time is handed out in equal slots by a weighted lottery. Class pre-emption (coin > user > background) is separate and strict (`what/is/the/architecture/of/cointos.md`).

**Who is not in the draw.** A thought still reading its context keeps its lane until the read is done. A generating turn keeps its lane for `scheduler.slice_seconds` (30) from when its opening read finished. An agent returning within its tool-call grace takes back the lane kept for it.

**The draw.** Time is cut into global slots of `slice_seconds` (`scheduler.slot`: `now // slice_seconds`). For every waiting thought and every holder whose slice is over, `scheduler.draw` seeds `random.Random` with `"<agent>:<slot>"`, takes a uniform `u` and returns `u^(1/weight)`. Highest lot first. This weighted-sampling key makes an agent's chance of winning proportional to its weight. Because the lot is seeded, it is the same on every scheduling pass within a slot (decisions are stable and reproducible in tests) and is redrawn at the next slot.

**Weights** come from the task role via `scheduler.weights` in `config/cointos.json` (worker 4, integrator 4, manager 2); unlisted roles (gardener, steward, auditors, operator) and taskless thoughts (Coin, user sessions) weigh 1. `lanes.begin` stamps the weight on the thought when it starts. Example: one worker against one gardener wins about 4 slots in 5; a gardener against three workers wins about 1 in 13 and waits about 6.5 minutes on average.

**Outcomes.** The winner holds the lane for the slot; an expired holder that wins simply keeps it, avoiding a context switch. When a winner must displace someone, placement prefers the lane whose holder drew lowest, after the usual preferences (own/kept lane, warm lane, free lane, a generating rather than reading holder). Lanes are work-conserving: while an agent runs a tool, any waiting equal can use the lane.

**Starvation check.** Long waits by low-weight agents are expected behaviour, so `checks.py` does not alert on waiting time. "No agent starves" fails only when a waiting thought's lot beats a non-reading equal holder that is past its slice, and it has still not received the lane `checks.preempt_seconds` (15) after the later of its arrival, the holder's slice end and the slot start. That indicates the scheduler's choice is not being applied.

**Evidence.** `tests/test_scheduler.py` covers proportional shares (4:1 gives about 80% for both waiting and expired-holder contests), per-slot stability, in-slice protection and lowest-lot displacement; `tests/test_memory_and_checks.py` covers the starvation check.

Proof:

```bash
cd "$(git rev-parse --show-toplevel)" && python3 -m unittest -q tests.test_scheduler tests.test_memory_and_checks
```
