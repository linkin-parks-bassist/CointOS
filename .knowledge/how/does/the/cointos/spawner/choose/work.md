---
status: green
revised_at: "2026-09-26T09:24:56+10:00"
---

`ecosystem/spawner.py` runs every minute from `agent-spawner.timer` (a oneshot in `background.slice`). Each tick spawns at most one autonomous agent, and only when all of these hold:

- `config/spawner.json` has `enabled: true`;
- dispatch is not paused (`state/PAUSED`) and resource control has not halted it;
- David's own agent work is not active: no active job with a user-directed origin (`local_operator`, `telegram_contact`) and no active operator session. Autonomous work stands back entirely while David uses the machine for his own agent work;
- fewer than `max_active_agents` agent jobs are active, counting all sources.

It then picks the first match, scanning the projects listed in `config/spawner.json` `projects` (only listed projects are touched):

1. `what/is/urgent/*.md` with status `queued` or `in progress` → **worker**;
2. `what/is/queued/*.md` with status `queued` or `in progress` → **worker**;
3. `what/is/drafted/*.md` with status `drafted` → **manager** (break the idea down);
4. a project not surveyed for `survey_interval_seconds` → **manager** survey (queue the next steps from plan/state/next);
5. no steward check for `steward_interval_seconds` → **steward**, with a card drawn from the `steward-tasks/` deck (weights in `config/watchdog.json`).

An item already held by an active spawned job, or spawned within `item_cooldown_seconds`, is skipped. That stops a failed item from respawning in a tight loop. The job source is `spawner:<kind>:<item-or-workspace>`. Jobs run in the project's repository with the `ordinary` authority profile, reasoning plus tool-calling requirements, and the configured model preference (Qwen3.8-27B). They sit in the default priority band, below Sole Survivor, Coin and user-driven work, and are pre-emptible. State is in `~/.CointOS/state/spawner.json`; each spawn is audited as `spawner.spawned`. Run `scripts/spawner` by hand to see one tick's decision.
