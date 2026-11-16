---
status: green
revised_at: "2026-11-17T07:20:01+11:00"
---

Observe live production through the CointOS gateway, not direct native lane fixtures. Use GET /api/models for selected identity/phase and numeric fields from /api/ledger: per-thought prompt, held, generated, reading, rate and progress_at; recent switch restored counts, divergence common-prefix lengths and lane-state-loss events; agent engaged state; memory headroom, PSI and guard state. Never copy request bodies, tool contents, session exports or token vectors into monitoring evidence.

Combine that with Halogen /cache pool usage, hits/misses, eviction and relocation counters, and targeted engine messages about refused KEEP states or waiting for room. Hit ratio alone does not prove tail reuse: a full-context reread loop can still produce many intermediate prefix-cache hits. Confirm advancing generated counts, warm switch positions and no repeated reset to zero for the same thought. Original-prompt read bars can remain full while recovery reads generated tails.

Distinguish cache loss from changed input. A model restart requires a cold read. Compaction or a changed system prefix can invalidate cached continuation without a backend failure. Compare numeric held, next-prompt and divergence.common values before attributing a full read to eviction. Live observations included roughly 112k-token requests diverging at token 14,006, followed by smaller prompts. David confirmed he was away at the gym, ruling out a contemporaneous manual compaction; automatic client compaction is the supported explanation. The isolated NativeV2.test_native_compaction_persists_the_factual_anchor fixture passed and confirmed different system messages between normal and compaction requests, with nine tools in both. Numeric evidence is ~/.local/state/halogen-trial/compaction-prefix-probe.json; it used a local stub provider and disposable store, with no production gateway call.

OpenCode's documented default automatic compaction threshold is 15% below the context limit (at least 16k reserved), approximately 111k for 131072 tokens. Private OpenCode inherits ordinary compaction preferences; do not silently change them. See https://opencode.ai/docs/compaction and how/to/run/a/user/opencode/session/alongside/cointos.md.

The repaired synthetic 40k/36k interleave in ~/.local/state/halogen-trial/long-cache-retention-v2.json measured one pending input token per resumed generation step. why/does/halogen/reread/a/large/context/after/each/generation/burst.md owns that failure and repair. This does not prove that arbitrary simultaneous long contexts always fit.

The session-owned ~/.local/state/halogen-trial/stability-watch.py collects numeric snapshots to a mode-0600 JSONL file. Stop it when the requested monitoring session ends; it is not an installed perpetual service. Preserve existing requests while observing. Announce any necessary controlled restart before interrupting a live request, retain client history, restore up/go, and verify the gateway afterward. Long native fixtures require a stopped daemon and finally-based restoration; they must not compete with production scheduling.
