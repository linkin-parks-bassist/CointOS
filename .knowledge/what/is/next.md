---
status: green
revised_at: "2026-09-26T09:42:03+10:00"
---

The autonomy loop is live (roles, spawner, knowledge-tree queues, Coin kt tools). Next: let it run and fix what actually breaks.

1. **Watch the first autonomous rounds.** Check that manager surveys produce sensible `what/is/queued/` items in `~/Projects/CointOS/.knowledge`, that workers pick them up, update item status and commit, and that stewards report real findings. Tune `roles/*.md` and `config/spawner.json` from what happens; David owns the role wording.
2. **Two lanes.** Qwen3.8-27B should grow to two lanes once idle (`profile_minimum_parallel_sequences: 2`) and stay there, so two agents run at once. Confirm the reload happens and that the desktop stays responsive.
3. **Throughput.** Agents currently make roughly one tool call a minute on Qwen3.8-27B. Measure where the time goes (prefill of the roughly 3 KB role prompt plus knowledge-tree bootstrap, versus generation) before changing anything.
4. **Workstation guard.** Confirm autonomous work stands back when David starts his own local agent session, and that `cointos stop`, `halt` and `up` behave as documented (`how/to/operate/cointos.md`).
5. **Sole Survivor.** Still unproven live; qualify it on the next real or safely induced incident.
6. **Distillation.** Apply `global:how/to/approach/architecture-design.md` to the code as problems surface. `ecosystem/executor.py` and `ecosystem/resource_control.py` are the largest mixed modules; refactor causes at their owning layer rather than patching symptoms.

Constraints: worker tasks use exact Qwen3.8-27B, never 4B/8B-class models. Do not touch Avnet/professional data.
