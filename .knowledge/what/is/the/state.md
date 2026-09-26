---
status: "green"
revised_at: "2026-09-26T10:52:29+10:00"
---

Nothing of the core is built yet. This branch contains the knowledge tree, the role files in `roles/`, and a README.

The currently installed CointOS runs from `~/.CointOS` (source: git tag `archive/pre-rebuild`), with user units named `agent-*` and `cointos` on PATH. Current state:
- dispatch is paused and the spawner timer is disabled, so no agents are running;
- Coin, the dashboard (port 4200) and both models (Qwen3.8-27B, Qwen3.5-4B) are up.

`cointos halt` stops it and frees Lemonade and port 4200.
