---
status: green
revised_at: "2026-11-02T18:13:44+11:00"
---

Current accidental capability gaps, from source and per-run agent logs. These are defects or friction, not user policy; they are separate from the deliberate guards in what/are/the/cointos/agent/capability/requirements.md.

- **kt writes:** branch-publishing confinement omits `~/.knowledge/.tools` and `~/.local/state/knowledgetrees`; `kt_add`/`kt_rewrite` fail with EACCES. The edit allowlist covers only the worktree, so knowledge edits resolving to canonical paths are also denied.
- **Operators:** ad-hoc operators default to `standard`; standard operators cannot queue, correct tests, resume or replace, and project operators cannot publish product code. Verified product fixes can be stranded with no worker/integrator handoff. First Responders receive all abilities; ordinary operators do not.
- **Compaction:** OpenCode summary generation rejects tool calls, ending runs without receipts (`Tool call not allowed while generating summary`).
- **Read-only denials:** blanket `systemctl`/`dpkg`/lifecycle patterns deny `systemctl status|cat|is-active|list-units`, `dpkg -l` and `cointos resume|kill --help`.
- **Installation/toolchain:** there is no `sudo`/`apt`/pip/npm-g capability; required tools such as verilator must be installed by the user. Landlock also omits ordinary caches (`~/.cache`, cargo/npm/pip caches) and canonical build checkouts.
- **MCP/network:** factory roles have no station tools, so they get only knowledgetrees and CointOS MCP; a stationed Operator gets what its station grants. `webfetch`/`websearch` require the network ability, which construction tasks lack.
- **Landing granularity:** submission and landing compare whole registered commands. New commands and commands green on main must pass; only registered commands already red on pinned main qualify for exemption. A split implementation cannot claim assertion-level progress inside one covering command, and an already-red command can conceal changed failing assertions.
- **Recovery/retry:** workers, managers, integrators and operators have zero automatic fresh budget retries; infrastructure hiccups and some MCP finish timeouts become blocked work. Anti-loop guards should remain, but infrastructure retries should be distinguished from product refusals.

Source owners: `opencode.py` settings/write_paths, `stations.py`, `api.py` controls/queue, `contracts.maintenance_history`, `contracts.combined` and the landing gate, roles/_base and roles/integrator, plus live `state/events.jsonl` and per-run agent logs. The non-code merge-composition fix is separate and already applied. The submission-only rejection of baseline failures is repaired; command-level granularity remains.
