---
status: green
revised_at: "2026-09-20T05:09:51+10:00"
---

Local worker prompts are exactly the assigned task text plus newline. Source cli.prepare_next, executor model-switch, and Sole Survivor prompt preparation all write only the task text; render_context and the generated contract/role/registry briefing no longer exist in source or installed ecosystem/roles.py. The durable task contract still validates and schedules the job but is no longer serialized into the prompt.

Home, source, and installed AGENTS.md were retired at David direction (copies in /tmp/cointos-agents-retired-20260920). Source Telegram fast, deep control, and notification system prompts no longer read AGENTS; telegram.FAST_SYSTEM carries the two directly relevant identity and response-style instructions previously sourced there. The OpenCode KT hook owns startup bootstrap; complete delivery with the final proof summary is live-qualified on fresh worker task-73e862421c6f4c4e. See local:why/did/managed/opencode/workers/miss/the/knowledge-tree/startup/hook.md for the root cause and resolution.

The workspace registry is fully retired from prompts, contact routing, schema, and active config; authority profiles live in config/authority-profiles.json (version 1, seven profiles). OpenCode fresh sessions use the validated task workspace as --dir; legacy resumed sessions retain home for identity continuity.