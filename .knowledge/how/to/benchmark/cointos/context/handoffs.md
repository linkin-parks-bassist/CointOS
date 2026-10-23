---
status: green
revised_at: "2026-10-11T11:33:59+11:00"
---

Compare one physical slot that saves/restores alternating histories against two physical slots holding those histories resident. Keep weights, sampling, per-history context allowance and generated-token budgets fixed; issue requests serially so resident capacity is not confused with concurrent batching. Measure copy time, prefix verification, generation, whole handoff time and memory separately. Inspect every returned retained prefix. Preserve production recipe, pin, tasks and autonomy in `finally`.

`/tmp/cointos-resident-switch-probe.py` and `/tmp/cointos-resident-switch-evidence.json` use patched packaged Vulkan/MTP, production sampling, two public-code histories initially 8,198 tokens each, and 12 alternating 32-token steps (384 generated tokens per arm). One slot has 131,072 total context; two slots have 262,144 total, verified 131,072 per history. No snapshot save/restore occurs in the resident arm; selecting `id_slot` chooses its existing state.

| Arm | Generation tokens/s | Completion seconds | Copy seconds | Tokens/s including handoffs |
| --- | ---: | ---: | ---: | ---: |
| One slot, snapshots | 16.154 | 25.642 | 3.995 | 12.957 |
| Two resident slots | 15.967 | 26.159 | approximately zero | 14.679 |

Resident handoffs improve this short fixture 13.3%, without improving raw generation. Single-slot snapshots start at 694,322,892 bytes. Per-handoff restore is roughly 0.10–0.12 seconds and save roughly 0.20–0.24. Generation-time inference-cgroup peaks are 37.45/38.06 GB; these are not complete GPU/whole-machine memory measurements.

Exact retained-prefix assertions pass. Recipe, task/session/branch/worktree identities and autonomy restore; ten runtime checks pass. Output vectors and whole-task quality are not established. This is a serial native prototype, not deployed CointOS scheduling: validate occupied contexts, actual tools/reasoning, resident selection/eviction and paired GPU/host memory before adoption. The service owner explains current paired MTP snapshots; this comparison used target-only snapshots, and the backend benchmark owner holds decode comparisons. Thirty-second scheduler boundaries cause copies only when a different history replaces the lane, not whenever time expires.
