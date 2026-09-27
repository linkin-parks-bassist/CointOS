---
status: green
revised_at: "2026-09-27T17:05:50+10:00"
---

Full autonomous acceptance is not established. The specification defines the required scenarios; the plan lists remaining demonstrations.

Current layout verification on 2026-09-27: both services run from ~/.CointOS, its runtime tree is allowed everywhere through kt, and CointOS is paused with zero agents. All eight live cointos check invariants pass. The Todo continuation command was accepted through the API, survived reinstall/restart and repeated submission without duplication, and appears in the runtime command-queue leaf. Installed code/config/roles match the source. The source suite passes 98 tests, including actual kt queue publication, sorted-JSON priority persistence, integration acceptance and settlement retry. The sandbox retains its 217 passing tests. These checks do not demonstrate autonomous prompt quality or complete Todo behavior.

Historical evidence retained from the former plan: a two-hour soak on 2026-09-27 took 1,360 five-second samples. Its seven then-existing checks remained green; four agents appeared in 1,357 samples and three in the other samples; three sandbox items landed. This predates the integrator and bounded roles and cannot certify them, Coin timing or workstation/user priority. Recorded evidence paths are gitignored logs/evidence/m3-20260927.log and logs/evidence/lanewatch.log; those historical logs were not re-audited during the layout migration.

Earlier recorded bounded observations include token-level resume and chunked reading; 0.2–1.5-second slot save/restore; a shared 10,832-token start occupying 0.87 GB; first token 1.6 seconds after Coin pre-emption; suspended-startup silence recovery in 29.97 seconds; and a single-task halt/up retaining worktree/session, refunding its run and later delivering. These are prior observations, not current guarantees. Cold resume after reload and malformed continuation remain open defects.
