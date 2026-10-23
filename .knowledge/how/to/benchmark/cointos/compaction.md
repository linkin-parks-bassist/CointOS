---
status: green
revised_at: "2026-10-11T10:19:45+11:00"
---

Benchmark compaction without restarting managed agents. Preserve exact identifiers, completed tools, pending work, disabled execution, window limits and recovery.

## Cache break and candidate

OpenCode 1.18.35 flattens history and truncates tool outputs at 2,000 characters. CointOS pins system text, but missing declarations change template tokens. Live compaction changed 114,322 tokens to 44,335 with three common tokens; its later continuation recovered only an 18,729-token shared prefix.

The installed, disabled structured-v1 gateway requires a managed, tool-free summary envelope: instructions `c` and complete native flattened fallback `f`. Pinned declarations preserve rendering; tool-call decoding is disabled. Actual tokens plus output reserve must fit the window, otherwise use the tool-free fallback. Missing declarations also select fallback.

`patches/opencode-1.18.35-guarded-compaction.patch` dry-applies to checked source and preserves ordinary flattening when disabled. `scripts/patch-opencode-compaction-prototype` reproduces the tested compiled CLI with one 557-byte length-preserving change from the exact attach-fixed input hash. This compiled copy always emits envelopes and requires the paired header hook; never replace global OpenCode. The launch procedure owns the default-off, CointOS-only option.

Prototype SHA-256: `572e9e9f838c0a150558c8b412a50c3130acea0edd07288ab8da73b3b0a2380e`. The prototype executable remains unstaged.

## Checked boundaries

Native fixture evidence is `/tmp/cointos-compaction-shape-<suffix>/evidence.json`:

- `o58gq0x8`: header, history, identity, summary consumption and counter executed once.
- `wrrr44wo`: real renderer selects exact native fallback in a reduced window.
- `96hugjrl`: interrupted isolated server restarts and recovers through `finish_compaction`, without repeated counter execution.
- `5ihsnajw`: actual supervisor launches the reproduced private CLI with its paired header.

Tests cover exact fit, overflow, missing declarations, malformed/unmanaged envelopes and tool markup staying text. Tokenizer artifacts `/tmp/cointos-compaction-{envelope,long}-prefix-evidence.json` retain complete 8,420- and 89,416-token prefixes; the 135,316-token synthetic history selects a short fallback.

## Model evidence and remaining work

`/tmp/cointos-compaction-model-evidence.json` has four matched production-recipe trials: median prefill 17.509s flattened versus 2.415s structured, 86% less. Total including restore is 28.868s versus 12.257s; differing output lengths preclude decode-rate claims. Tiny summaries preserve the counter result without tool calls.

`/tmp/cointos-summary-protocol-quality-evidence.json` checks exact candidate rendering: 27,979 tokens, 27,651 shared with ordinary history, 864 output tokens in 239.38s. Identifiers and once-only work survive without tool calls or agent restarts, but planned checks become Blocked, completed verification becomes Active, and a pause is invented. Deployment acceptance fails. Source now instructs that pending checks belong in Next Move, Blocked requires an established obstacle, and Active excludes completed verification; it forbids invented pauses/dependencies. The corrected exact-rendering recheck `/tmp/cointos-summary-protocol-corrected-quality-evidence.json` completes 28,032 input/809 output tokens in 244.86s: no invented blocker or pause, correct identifiers/final results/counter. Active still duplicates explicitly unstarted next steps; initial failure values are omitted. This is acceptable limited fidelity evidence for controlled adoption, not broad quality certification. All agent/session identities survive. Small instruction-tail changes restore zero because the saved checkpoint extends past the mismatch, forcing another full read. Installed earlier checkpoints address small tail edits; the scheduler owns native reuse evidence. Custom native fixture `cb3w0aqb` preserves override instructions and history with once-only execution; compiled custom fallback omits the native history label while retaining content. The guarded source patch preserves that label. Gateway/launch support is installed but disabled; managed compaction recovery and sustained gains need observation.
