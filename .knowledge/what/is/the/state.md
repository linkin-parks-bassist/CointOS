---
status: "green"
revised_at: "2026-09-26T15:51:37+10:00"
---

CointOS runs from this checkout as the pre-emptive design in `what/is/the/architecture/of/cointos.md`, rebuilt from scratch on 2026-09-26 (the earlier request-scheduling core is gone). The work since `ab1dd28` is not committed.

**Code** (`cointos/`): `backend_llama.py` (all Lemonade and llama-server specifics), `scheduler.py` (pure policy), `lanes.py` (thoughts, steps, switches, snapshots and their tiers, shared starts), `gateway.py` (OpenAI endpoint, API, dashboard), `work.py` (tasks, spawner, agent lives), `memory.py` (headroom, distress), `checks.py` (invariants), `daemon.py` (tick, models, guard), `state.py`, plus `agents.py` (OpenCode), `queues.py`, `cli.py`, `coin.py`, `kt_mcp.py`. Unit tests: `tests/` (scheduler policy, memory rules, self-check), green. `kill -USR1` on the daemon writes every thread's stack to its journal.

**Seen live:**
- The backend: exact token-level resume, chunked reading, slot save and restore (0.2–1.5 s), and conversations re-rendering to the very tokens generated, so a next thought reads only what is new.
- Pre-emption through the gateway: a Coin thought arriving while both work lanes were busy got its first token 1.6 s later; the pre-empted thought was saved and restored warm and finished.
- Tokens as context identity: two concurrent conversations of one owner each kept their lane.
- A shared start of 10,832 tokens (0.87 GB) saved from two worker contexts.
- One item (fizzbuzz) merged to the sandbox's `main` under the old core.

**Not yet seen:** agents completing thoughts under the turn model (it went live at 15:49), the Milestone 3 run end to end, a real Telegram round trip with Coin, the unattended hour and the soak.

**Lessons that shaped the design (2026-09-26):** a 30 s slice kept cold 36k-token reads from ever finishing, so reading holders are not pre-empted by equals; llama-server cancels a dropped read only minutes later, so steps are never cut; snapshots in `/dev/shm` are charged to Lemonade's cgroup, and 42 GB of superseded snapshots made systemd-oomd kill Lemonade, so a conversation keeps one snapshot, headroom counts the server's budget, and snapshots move to disk before being forgotten.

**Installed:** `cointosd.service` and `cointos-coin.service` are enabled and run this checkout; `~/.local/bin/cointos` points at `bin/cointos`. The old system (`~/.CointOS`, units `agent-*`) is stopped and its units disabled; nothing of it was deleted. Snapshots: `/dev/shm/cointos-contexts` (made writable for the `lemonade` user) and `~/.cache/cointos/contexts`. Configured projects: only `sandbox` (`~/Projects/cointos-sandbox`), by David's choice until the soak passes.
