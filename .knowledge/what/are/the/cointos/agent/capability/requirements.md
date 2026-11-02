---
status: green
revised_at: "2026-10-26T12:25:07+11:00"
---

CointOS agents are trusted local agents. The user's requirement is broad local capability: do not invent tool or access restrictions. Current launch restrictions are mechanics to review, not default policy. Only these deliberate guards remain:

- Knowledge leaves are atomic/deferential; kt's bounded rewrite growth guard deliberately adds friction to long leaves. The remedy for a bounce is split or defer the leaf, not weaken the guard.
- Per-reply reasoning caps 256/384/1,024 (low/medium/xhigh) are deliberate Qwen3.8-27B performance control; without a forced stop the model reasons indefinitely. Do not remove them as a capability restriction.
- Test-contract/protected-test separation, independent review, explicit user holds and private-root access boundaries remain deliberate authority boundaries.

how/to/launch/opencode/for/a/cointos/agent.md owns the concrete launch settings; what/are/the/cointos/agent/capability/gaps.md owns current accidental gaps.
