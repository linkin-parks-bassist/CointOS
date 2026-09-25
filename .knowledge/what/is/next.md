---
status: "green"
revised_at: "2026-09-26T09:11:42+10:00"
---

Next: build the missing autonomy layer on top of the existing scheduler, in this order. Stop live-qualifying scheduler edge cases unless one actually breaks; the loop running on its own is the priority.

1. **Coin live check.** David asks Coin to look something up and to add a leaf, over Telegram. This confirms the new `kt_*` tools work end to end.
2. **Roles.** Write the five starting roles: `sole_survivor`, Cointelprofessional (`_control-plane`), `steward`, `manager` and `worker`. Delete the other legacy role files and cut `ecosystem/roles.py` down to match. Design owner: `what/is/the/intended/replacement/for/existing/agent/roles.md`.
3. **Queue layout.** Settle the item leaf shape and branches (per-project `~/Projects/<repo>/.knowledge/`, plus `~/.CointOS/.knowledge/what/is/{queued,pending,urgent}/`) by trying them. Leaves state current truth, never logs.
4. **Spawner.** When a GPU lane is free, spawn one agent. Queued items get a worker, unchunked ideas get a manager, and otherwise steward work runs. Each agent does one small step and exits. Fold the watchdog's `steward-tasks/` deck into steward work.
5. **Leave it running** and judge by what David sees: the GPU stays busy, drafted ideas and queued work visibly advance, and nothing falls over.

Constraints: worker tasks use exact Qwen3.8-27B, never 4B/8B-class models. Do not touch Avnet/professional data.
