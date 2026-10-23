---
status: green
revised_at: "2026-10-14T23:54:38+11:00"
---

Unexplained. On 2026-10-05, two requests after a `cointos_send` to `user` lost their checkpoints and read about 29k tokens cold, though each prompt grew only about 155 tokens. Ruled out: the pinned system prompt, OpenCode pruning/compaction, the Qwen template and mid-loop rewording. `mcp.catalogue` dropped role tools when its ledger lookup failed; tool pinning now neutralizes that. If it recurs, `prompt rewritten` names the cause.
