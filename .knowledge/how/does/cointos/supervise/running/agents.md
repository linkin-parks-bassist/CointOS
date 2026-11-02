---
status: green
revised_at: "2026-11-03T07:06:44+11:00"
---

A Supervisor (`roles/supervisor.md`, task kind `supervise`) watches over a run. The user wants basically every run under about 30 GPU minutes where possible, so long runs are not normal, though the default worker budget remains 90 minutes. A Supervisor often just waits and looks in, but it must judge what the time is going on rather than how reasonable the agent sounds: the first one retired after seeing an implementer debug its own simulation of hidden tests. The user's rough hope is mostly staying and watching, with retiring and intervening each uncommon. Those proportions are deliberately kept out of its prompt so it does not treat them as quotas.

`recovery.supervise` requests one when a run's GPU generation passes each multiple of `recovery.supervise_every_seconds` (1,200) if none is live, for every role but itself, gardeners and tree auditors, and never for a run past its budget. GPU time is used because wall time mostly measures waiting. A run a Supervisor retired from therefore gets a second one at 40 GPU minutes. Any agent can also dispatch one with `task`.

It starts past `spawner.max_agents` while memory allows. Its own scheduling class preempts background runs on the GPU, below Coin and the user, and memory pressure still stops it. Its budget is 1,800 seconds and 40,000 tokens. It reads `cointos transcript`, waits on `cointos_inbox` with `wait_minutes` (at most 9) and leaves files alone.

When it steps in, its main tools are `cointos_send` and `cointos_revise`. A revise clears the run's context and replaces its assignment with the Supervisor's updated brief, while branch and uncommitted files stay. The brief preserves the end goal, reflects the new jumping-off point and changes the instructions as needed. It revises instead of letting a run compact, and a revise cancels the Supervisor at once (`api.revise`). A job too big goes to `cointos_split`; a malformed one goes to `cointos_recover`, which fails the run so a First Responder comes.

The subject is told who is watching and can message it. Supervisors coordinate through `cointos_peers` and `cointos_send`.

`lifecycle.evidence` refuses its first complete receipt while the run is going and accepts the next, so it must insist to retire. A blocked receipt summons no First Responder. When the run ends, an unstarted Supervisor is cancelled, and a running one is told to dispatch any follow-up and is cancelled after `recovery.supervise_wrap_up_seconds` (120).

Its role lists what implementers may not do: probes, scope expansion, test edits, unrequested design or knowledge work, endless verifying. `opencode.settings` also denies implementers commands and edits with "probe" in the name, for runs started after that change. Early live observation: one Supervisor revised a compacting worker with a detailed brief, but that brief wrongly sent the worker after its hidden tests, which led to the guidance against it.
