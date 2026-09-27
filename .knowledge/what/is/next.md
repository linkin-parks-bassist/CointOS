---
status: green
revised_at: "2026-09-27T12:19:48+10:00"
---

David authorized a fresh C JSON-parser exercise through ordinary sandbox intake. Keep its brief exclusively about product behavior and acceptance; infrastructure policy supplies decomposition, task sizing, review and handoffs. The prior test runs remain discarded. OpenCode stays at 1.18.32 by explicit request; no migration work is active.

1. **Observe the JSON-parser exercise through ordinary CointOS intake.** Let the manager derive the work, workers implement it and the integrator review/land it. The current sizing heuristic is 10–20 minutes of substantive Qwen3.8 work per task, excluding prefill and lane waits, with no duration timer. Check actual handoffs and final software acceptance without manually decomposing or implementing this test for the agents. A separately scheduled recursive reviewer hierarchy remains future design.

2. **After restoring ambient configuration, validate bounded gardening live.** Demonstrate one random 1–3-leaf pass, one non-green batch and one separate structural audit. Code/tests enforce selected batch size, separate audit cadence, per-tree exclusion and landed clean completion. Do not launch an exhaustive whole-tree repair as a routine pass.
3. **OpenCode unchanged.** Keep 1.18.32; migration assessment is retained in the launch procedure for a future decision, not current work.
4. **Remaining acceptance:** process-kill recovery within 30 seconds; ten visible Telegram replies within 15 seconds under load; workstation responsiveness and user-class priority; halt/up during a multi-agent run; reboot recovery of eligible disk snapshots. Coin timing needs David's messages or an explicitly authorized test; this refresh sent none. Prior soak evidence covers checks, concurrency and delivery only.
5. **Deferred scheduling design:** ambient/focused operation, runtime-adjustable project and task-kind priorities, and weighted round-robin or counted shares. David explicitly deferred implementation; the present change is configuration only. Task admission rank and GPU class priority are distinct today.
6. **Open design work:** robust interruption semantics at the gateway/OpenCode boundary; a CointOS MCP control surface; memory reshape/fork choices; and network restrictions beyond prompt/OpenCode denials. Server RAM prompt caching is already disabled in both configured model shapes and operational timeouts are already centralized, so neither is pending approval.

Resuming through cointos go is authorized for this exercise. Observe pickup and report failures honestly rather than coaching the product brief. Sole Survivor remains off the roadmap.


**Temporary test configuration and restoration.** max_agents=2; work-model lanes=1 and ctx_size=131072; trees=[] disables routine tree work. Only the JSON manager is retained from the four-agent start, continuing the same session/worktree. The unchanged survey interval may admit a future survey; this is not a project-focus mode. To restore the earlier ambient configuration, set max_agents=4, work-model lanes=2 and ctx_size=262144, and restore trees to [{"name":"cointos","path":"~/Projects/CointOS","tree":".knowledge","main_branch":"rebuild/simple-core"},{"name":"sandbox","path":"~/Projects/cointos-sandbox","tree":".knowledge","main_branch":"main"}]. A lane-shape change needs a controlled model reload; daemon restart alone does not guarantee an uninterrupted in-flight OpenCode reply.


**Resume/cache follow-up.** The one-lane restart retained the manager session but discarded its snapshots as conversation-diverged, causing a full 27,589-token read. Determine the differing prefix before claiming warm restart. Also inspect cancelled-owner snapshots reappearing during shutdown/in-flight saves. Neither finding calls for interrupting the current parser run.
