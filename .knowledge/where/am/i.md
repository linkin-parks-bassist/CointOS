---
status: green
revised_at: "2026-09-26T10:52:10+10:00"
---

This is `/home/david/Projects/CointOS` on branch `rebuild/simple-core`, the source of CointOS, David's autonomous local-agent ecosystem.

Read these first, in order:
1. `what/is/cointos.md`: what the system is for.
2. `how/to/keep/cointos/simple.md`: how CointOS is built and changed.
3. `what/is/the/architecture/of/cointos.md`: the design.
4. `what/is/the/spec.md`, `what/is/the/plan.md`, `what/is/the/state.md`, `what/is/next.md`: requirements, milestones, current state and the next step.

Facts about the machine, the models, Lemonade, OpenCode and Telegram are under `what/are/` and `how/`. Existing code that fits the architecture and can be reused is listed in `where/are/reusable/cointos/parts.md`.

A previous CointOS installation runs from `~/.CointOS`, with Coin on Telegram and `cointos` on PATH. It shares Lemonade and the GPU, so stop it with `cointos halt` before live-testing. Never touch `~/Avnet` or professional data.
