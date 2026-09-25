---
status: green
revised_at: "2026-09-20T14:59:46+10:00"
---

David suggested on 2026-09-20 that CointOS might eventually expose job inspection and control through an MCP, following the KT structured-tool experience. This is an idea, not an authorized implementation or settled design. Current read-only operator inspection uses scripts/worker-log-summary --active for managed jobs and scripts/worker-log-summary TASK --tail 25 for one durable log. Blocker: the tool surface, authority rules, and need relative to current CLI/control interfaces have not been chosen. Next check: when operator-interface work resumes, define a narrow read-only status surface first and evaluate how mutating actions would preserve existing CointOS authorization and audit semantics.
