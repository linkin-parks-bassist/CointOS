---
verified_at: '2026-09-11T15:40:39+10:00'
verified_by: codex /root
scope: project local
source: README.md; current project knowledge; pre-99318d9 Git history
verification: Read the current overview, status, and system map; checked the named top-level source and runtime directories exist.
review_when: Recheck when the product boundary, repository location, or first live vertical slice changes.
---

CointOS is the personal, local-first agent orchestration system in
`/home/david/agent-ecosystem`. It represents work as durable filesystem records,
runs local inference through Lemonade/OpenCode, separates responsive contact from
deeper work, and retains append-only evidence. `README.md` is the human entry point;
`what/is/architecture/of/cointos.md` explains component flow and
`what/is/current/project_priority.md` owns the immediate implementation seam. Do not
infer live service health from checked-in descriptions; use
[runtime truth](../../where/is/runtime_truth.md).
