---
status: "green"
revised_at: "2026-09-26T08:51:02+10:00"
---

Roles are being rebuilt from scratch around three classes (David). The current contents of `roles/` are not wanted. The target starting set is **Sole Survivor, Cointelprofessional, steward, manager and worker**. Roles then diversify within each class as practice shows the need.

- **Steward class:** dedicated to keeping the system itself alive and healthy. It includes:
  - **Sole Survivor:** automated incident diagnosis and recovery. It smartly and quickly takes the system down and brings it back up.
  - **Cointelprofessional ("Coin"):** the always-available remote-control and contact surface.
  - **Steward roles:** routine system maintenance.
- **Managerial class:** creates and maintains priority queues of work. It turns David's drafted ideas, submitted to-dos and project needs into ordered, small, elaborated, manageable chunks, and it reviews and audits results. Decomposition (the dissolution pipeline in `what/is/architecture/of/cointos.md`) and "what should happen next" judgement live here.
- **Worker class:** takes items from those queues and carries them out: implementation, testing and similar concrete steps.

The manager/worker split is how CointOS reconciles "agents act on their own judgement" with "local models get only small concrete tasks". Judgement about *what* to do is itself a managerial role's small, bounded task. Workers exercise judgement only about *how* to do their item.

**Queues live in knowledge trees** (David's intended direction, pending how it works in practice). Each queued work item is a leaf whose answer holds the item's current brief and status. Managers write and reorder these leaves, and a worker's "look around" is reading them. An item leaf states current truth, never a progress log. The exact branch layout, the item leaf shape and how the GPU scheduler picks up items are not yet designed.

**Coin edits knowledge trees directly.** Cointelprofessional must have knowledge-tree read and edit capability so David can draft ideas, adjust queues and correct knowledge through Coin. Coin currently has no knowledge-tree tools; this is required work.

Knowledge-tree machinery owns general behaviour (orientation, procedures, recording knowledge). Roles express only the distinct remaining responsibilities.

**Current runtime:** all 19 Markdown files under `roles/` are empty in source and installed runtime, so agents receive no role-specific guidance. `ecosystem/roles.py` still registers 15 legacy role labels, all with the same neutral advisory capability baseline; role context grants no execution authority. Autonomous work currently comes only from the watchdog's periodic `steward-tasks/` deck: ten maintenance-review cards chosen by `ecosystem/steward_tasks.py` from weights and maximum intervals in `config/watchdog.json`. That deck is cron-like templating. It should become steward-class work, with anything project-shaped moving to managerial queues. Keep deterministic watchdog liveness checks and trusted scheduling provenance as system mechanisms, separate from roles.
