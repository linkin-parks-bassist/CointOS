---
status: green
revised_at: "2026-10-23T22:27:12+11:00"
---

web/dashboard.html is self-contained. Hash routes select home (#/), project (#/<project>) and task drawer (#/<project>/<task id>, or #//<task id> on home). The header holds the brand, freshness stamp, Queue work, Run operator, Spawn scout and the run switch (Running/Paused; stop or go at once; paused it turns accent and reads Resume agents, as does the empty agent area). One tile strip follows: generation, prefill, MTP acceptance, Agents (held lanes, waiting thoughts), Queue (ready + blocked), Landed · 24 h (all-time count beneath) and Memory. Then active Coin and every live agent, then Work.

Performance tiles show one-pole EMAs (performance.py, alpha = 1 - exp(-phase_seconds / 10)); generation and prefill advance independently and hold when inactive; MTP divides smoothed accepted/proposed draft rates; prefill excludes cache restore and snapshot I/O; unmeasured fields show a dash; restart resets them. Coin busy reports carry PID/boot/start identity so stale busy state hides after exit. GPU counts use held lanes.

Controls share one vocabulary: .btn buttons (filled .go for the next step), .seg segmented choices (pressed = current), .switch on/off squares and one styled select face. No native confirm/prompt dialogs remain. Reversible actions run at once; Cancel, project Remove and Clear finished history arm in place (first click relabels and fills the button, a second within four seconds runs it). Cancel sends reason "cancelled from the dashboard".

Home shows project cards (open counts, project_about, pipeline counts, landed mix, active agents/latest landing) and Add project (sheet: add existing path or create new name, priority). A project page heads with name, about (three lines, click for all), Branch and Repository, and settings: Enabled switch (disabling stops its agents), Priority High/Normal/Low = 50/100/200 (lower runs first; others classify by <100/100/>100) and armed Remove (then home). Messages, Machine and Recently form a side column; project pages put them below the full-width main area. Machine holds slice and generation-step selects, the viewer-windows switch, lanes, memory and Diagnostics. Recently hides lane-switch, snapshot, tool-history, divergence, viewer and reasoning-cap events unless its Machine events switch is on.

Messages lists the last 40 messages to the user, newest first, clamped until clicked; those after a browser-local seen mark are flagged (a first visit flags the last day). Reply sends to the sender's inbox while its task is active. Reading never acknowledges delivery.

Diagnostics appear once, collapsed, headed by actual problems; dependency and ownerless-recovery issues link readable titles to the drawer with blockers; raw details stay folded. Presentation only, never a repair trigger.

Pipeline joins queue records and item tasks by project:item, excluding cancelled/superseded work. Classification order: Landed, Integrating, Review, Building, failed (no live record; shown only in Failed history), Blocked, Ready. Steps Blocked → Ready → Building → Review → Integrating → Landed show six chips (Landed: latest four, no summaries) plus overflow, each only as tall as its chips; arrows animate for live next steps. landedKind/landedMix distinguish implementation, tests, hidden tests, skeleton, integration and planning.

Names: work items split at task-<n>, title-case, keep acronyms, render s<n> as sections. taskName names other tasks by their own title with kind and place as context ("Dr Guide Finish", "Operator · System") or by kind when untitled (Loose ends, Garden); Work, drawer and Messages share it. Role colors distinguish workers, integrators, managers, upkeep and Coin. Cards show wall/GPU time (loading/reading/generation only), tokens, rate and footer clocks; below 470px only the current pipeline stop is named. /api/live updates cards, memory and performance at 10 Hz; /api/ledger arrives each second.

Cards, chips and rows open the drawer; Escape or the scrim closes it. Its controls: Resume (held), Pause, Message, Budget (a running task's only grows), Revise brief, Hold/Release, with Cancel task set apart; then Queue ⇈ ↑ ↓ ⇊ and Reasoning Low/Medium/Extra high segments. Facts include receipt and brief; recovery tasks resolve repair_origin and work_frontier shows owners/continuations. Queue controls follow record/repair_origin; cancelling a controller differs from withdrawing its originating work.

Work lists In progress, Waiting for the integrator, Up next and Queued work, then Done/Failed count buttons opening one list, and Clear finished history. Row controls: running → Message/Pause; held → Resume; queued → Hold/Release, ↑/↓; quiet ones show on hover or while armed, always on touch.

Forms open in one modal sheet keeping errors beside its button: Queue work → queue; Run operator → run-agent (abilities as toggles); Add project → project-add/project-new.
