---
status: green
revised_at: "2026-09-14T22:40:40+10:00"
---

CointOS sets model, small_model, and agent.compaction.model to the selected Lemonade model, and compaction.auto to true. This keeps normal OpenCode compaction inside a model whose context/output allowances were qualified for this launch. Letting a heuristic choose another small model would require its own residency and capacity qualification and could introduce a second stale capacity belief.

The wrapper does not replace OpenCode's compaction algorithm or create a CointOS handoff prompt. It reads back auto-compaction and the selected compaction/small-model settings, rejecting an explicitly disabled compaction agent. This is a current design choice for reliable local launches, not a requirement that all future compactions always use the main model. Independently qualified auxiliary compaction models could be supported later. Owner: ecosystem/inference_proxy.py apply_opencode_capacity; ecosystem/opencode_launch.py verify_server_capacity.
