---
status: green
revised_at: "2026-11-03T14:44:19+11:00"
---

A Supervisor (`roles/supervisor.md`, task kind `supervise`) watches over a run. The user wants basically every run under about 30 GPU minutes where possible, though the default worker budget remains 90 minutes. A Supervisor often just waits and looks in, but it must judge what the time is going on rather than how reasonable the agent sounds. The user hopes most will stay and watch, with retiring and intervening each uncommon. Those proportions are kept out of its prompt so it does not treat them as quotas.

`recovery.supervise` requests one each time a run's GPU generation passes a multiple of `recovery.supervise_every_seconds` (1,200) and none is live. That covers every role except Supervisors, gardeners and tree auditors, and never a run past its budget. GPU time is used because wall time mostly measures waiting. So a run whose Supervisor retired gets a second one at 40 GPU minutes. Any agent can also dispatch one with `task`.

It starts past `spawner.max_agents` while memory allows. Its scheduling class preempts background runs on the GPU and sits below Coin and the user. Memory pressure still stops it. Its budget is 1,800 seconds and 40,000 tokens. It reads `cointos_log`, waits on `cointos_inbox` with `wait_minutes` (at most 9) and leaves files alone.

To step in, it mainly uses `cointos_send` and `cointos_revise`. A revise clears the run's context and swaps its assignment for the Supervisor's updated brief, keeping the branch and uncommitted files. The brief keeps the end goal, starts from the run's current progress and changes the instructions as needed. It revises a run rather than letting it compact. A revise cancels the Supervisor at once (`api.revise`).

The user wants work escalated to a manager where appropriate, because that clears blockages and adds slack. A job too big goes to `cointos_split`, especially one already revised, recovered or retried. A malformed one goes to `cointos_recover`, which fails the run so a First Responder comes.

An implementer that has read its hidden tests is revised at once, by the user's decision: a revise removes them from its context and a message cannot. The brief is written as if it never happened. Only a Supervisor's look catches this, after the fact, because Git objects stay readable and code written from the tests stays on the branch. The hidden-test policy decision is still open in what/is/the/plan.md.

The subject is told who is watching and can message it. Supervisors coordinate through `cointos_peers` and `cointos_send`.

`lifecycle.evidence` refuses its first complete receipt while the run is going and accepts the next, so it must insist to retire. A blocked receipt summons no First Responder.

`lifecycle.stand_down` ends a Supervisor once no agent in `L["agents"]` runs its subject, whatever the subject task's status. An unstarted one is cancelled. A running one is told to dispatch any follow-up, then cancelled after `recovery.supervise_wrap_up_seconds` (120). Each agent holds about 15 GB, so a Supervisor kept for a subject waiting in review blocks the integrator.

Its role lists what implementers may not do: probes, scope expansion, test edits, unrequested design or knowledge work, and endless verifying. `opencode.settings` also denies implementers commands and edits with "probe" in the name, for new runs.
