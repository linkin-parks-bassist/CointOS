---
status: green
revised_at: "2026-11-11T11:38:06+11:00"
---

Source managed launches select OpenCode2.2.6 with opencode_v2=true. opencode.py owns run configuration, units, servers and observation; opencode2.py owns the native API/recovery boundary; sessions.py owns retained-history migration. Host override: `~/.local/lib/cointos/opencode2/node_modules/.bin/opencode` symlinks to canonical 2.2.7; David required all older binaries removed, including the V1 exporter. Source provisioning/preflight still pins old versions and needs reconciliation before reuse. Managed stores remain separate; execution on 2.2.7 is unqualified. Surviving V1 units retain their executable, configuration and hooks; run/server metadata selects the matching transport/viewer.

Admission exclusively reserves state/agents/<id> before preparation. Exact task/run or receipt ownership governs adoption. Thread/key/preparation failure preserves waiting work and evidence; unexpected unreceipted termination requires canonical recovery. Authority reads reject malformed/nonregular/symlink data rather than inventing defaults.

Every V2 assignment has a private versioned XDG store, local model catalog and mode-0700 per-run scratch. COINTOS_SCRATCH/TMPDIR identify scratch; cwd and PWD explicitly identify the assigned worktree because V2 has no run --dir. Existing scratch paths refuse without clearing/adoption. Kernel read/write confinement, insulated source, runtime-rooted observer KT and rewrite-state permissions remain in force. Local knowledge registration adds no access grants. Hardcoded external temporary paths are not rewritten.

A private authenticated loopback serve process precedes run --server URL --format json --auto with title, cointos/default and optional retained session. Password/config/log files are mode0600. Clients/viewers receive the matching password; no shared desktop service is used. Native JSON events already retain sessionID/part/step_finish fields. Recovery controls project native events into the same observer format. Transport reports execution facts, never completion authority.

Configuration retains:
- only the CointOS gateway provider, configured through native providers/package/settings with @opencode/ai/providers/openai-compatible; native model transforms remove other providers. Legacy V1 provider/npm/options with disabled timeouts leaves V2 without a model route;
- actual per-slot context capacity, ctx_size/(slots or lanes), currently131072 for the three-slot resident recipe, and configured output limits;
- disabled provider request/header/chunk timeouts, sharing, autoupdate, automatic compaction and file watching; lifecycle owns stalls;
- KT/CointOS MCP and only station-granted additional servers, with role/run-bound identity and existing validation/API timeout;
- shell command/path denials and inherited kernel confinement. Native subagents, interactive questions and OpenCode session/worktree mutation tools are removed; task ownership remains CointOS's. Capability requirements/gaps remain separately owned.

V2 uses shell/subagent names and execute for exact MCP catalog signatures. The native plugin keeps KT declarations role-scoped, replaces generic harness prose, refreshes the native catalog and appends bounded observed facts to compaction responses. Recovery and prompt-contract owners specify those boundaries. No V1 attached-event patch is applied. The hash-pinned V1 structured-compaction prototype is incompatible with managed V2 and refuses rather than silently selecting the wrong binary.

Generation budgets, explicit grants and reasoning effort retain their existing owners. The installed original-steer trial has no source-default per-reply reasoning caps; installation must preserve its actual configuration.

Use cointos agents/watch/view and the owned unit journal. Native tests use local stub providers, disposable stores and uniquely named units, never the model gateway. Passing transport fixtures does not establish judgment, compaction fidelity or unattended throughput. The harness assessment owns rollout status and remaining acceptance.
