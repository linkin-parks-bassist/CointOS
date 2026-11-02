---
status: green
revised_at: "2026-10-24T19:13:42+11:00"
---

Use the configured cointos/default provider and launch opencode --model cointos/default. Its OpenAI-compatible endpoint is http://127.0.0.1:4200/v1 with an ordinary user key and disabled request/header/chunk timeouts. This shares the already loaded GPU model and scheduler. User requests outrank background work at native step boundaries; Coin outranks user work. An independent Lemonade engine bypasses that scheduler.

Keep a normal interactive OpenCode process/session open for warm follow-ups. With an actual persistent 1.18.35 server, a foreground request displaced active background generation in about 0.55 seconds after observation, restored 28,859 of its 28,883 prompt tokens in 1.09 seconds, and returned PRIORITY_READY. The full save/restore switch took 1.35 seconds. Background work subsequently restored and continued. A same-server follow-up completed in 34.6 seconds including reasoning and a knowledge proof; the later foreground answer under load took roughly 29 seconds from CLI invocation. These are small acceptance probes, not broad latency percentiles.

Cold starts remain costly with the current 27B model and global tools/skills: about 27,800 prompt tokens and 82–107 seconds in these probes. Restarting OpenCode can also change remote MCP tool schemas. A separate-process resume took 75.5 seconds and reread the prompt; snapshot headers first differed at token 12,406 because a remote tool's version enum changed. Its longer cached checkpoint correctly refused reuse. Do not pin obsolete tool schemas to hide this mismatch. Warm GPU scheduling works; cold-start/tool-schema and reasoning latency remain real limits to calling the experience instant.

Private evidence is under ~/.local/state/cointos/default-model-acceptance/: opencode events/logs, attached-session events and attached-priority.json with scheduler samples/native switch timings. Tests preserved the pre-existing paused autonomy setting and did not perform managed-product work. A browser was unavailable; dashboard verification covers API and JavaScript, not visual browser acceptance.
