---
status: green
revised_at: "2026-10-23T21:03:24+11:00"
---

Agents are OpenCode sessions using only the CointOS gateway. The on-disk CLI is ~/.local/bin/opencode 1.18.35; surviving servers retain launch settings. opencode.py owns configuration, units, supervision and events; runs.py owns admission/adoption; prompts.py owns assignments.

Admission exclusively reserves state/agents/<id>/ before preparation. The ledger lock prevents unregistered followers. Thread/key failure leaves work waiting. Authority reads reject malformed, unreadable, duplicate-field and nonregular/symlink files; only absence initializes defaults. Adoption requires exact task/run or current receipt ownership; displaced work requeues and receipted survivors are watch-only.

Each new run creates mode-0700 scratch inside its reserved directory. COINTOS_SCRATCH and TMPDIR identify it for server, client and descendants. Existing paths, including symlinks, refuse launch without clearing/adoption. Agents use fresh invocation directories and remove only their artifacts. Scratch remains with run evidence. This avoids deterministic names, not hardcoded /tmp collisions. Adopted processes retain their environment. Builds that hard-code shared temporary paths still need separate isolation; scratch environment variables do not rewrite their behaviour.

Preparation registers checkout knowledge trees through kt before confinement, preserving access policy. Native kt_add can establish local answers without global-policy write access; confinement owns MCP/kernel evidence.

Mode-0600 opencode.json contains the gateway key and:

- local /v1 cointos provider through @ai-sdk/openai-compatible, per-lane context/output limits;
- disabled provider request/header/chunk timeouts; lifecycle owns stalls;
- knowledgetrees/CointOS MCP enabled, other global servers disabled;
- MCP timeout validation_seconds plus twice api_seconds, in milliseconds;
- disabled sharing, autoupdate and file watching;
- role/ability controls for web, lifecycle/services; no sudo, package installation or Git push. No machine-local directory blacklist is injected; kt privacy is separate from normal task write confinement.

Installed construction servers use native-accepted 1,820,000 ms MCP configuration. The versioned 1.18.35 implementation applies it to execution and connection/catalogue calls; this verifies configuration, not completed slow validation.

New launch environments capture COINTOS_COMPACTION_CONTEXT_COMMAND for their exact task/run. opencode_resume.mjs identifies native summary metadata through the SDK, then invokes a bounded read-only helper and appends task/bindings, local HEAD/manifest count and remaining budget including grants. Unavailable facts remain explicit; failed metadata lookup leaves text unchanged. It neither reads hidden packet bodies nor verifies model prose. Existing servers retain loaded plugin/environment. Compaction recovery owns native transport evidence and unresolved fidelity.

structured_compaction defaults false/header off; enabling requires the checked CLI hash. Captured executable/header remain coupled; its benchmark owns acceptance.

Reasoning effort is pinned task metadata. Per-reply caps are 256/384/1,024 for low/medium/xhigh; interruptions retain charges. Test writers/managers/integrators default medium; reviews use their own settings.

Run files live in ~/.CointOS/state/agents/<id>. Use cointos agents, watch, view and journalctl --user -u cointos-agent-ID.service; watch/view need terminals. Bounded state/events.jsonl retains diagnostics without prompts. OpenCode V2 remains deferred pending supervision/tools/permissions/events/recovery compatibility.
