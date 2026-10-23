---
status: green
revised_at: "2026-10-23T22:27:22+11:00"
---

Use **Clear finished history** at the right of the foot of the dashboard's Work panel, beside the Done and Failed count buttons. It is pressed twice: the first click arms it in place, and a second within four seconds runs it. It calls the daemon's `POST /api/clear-task-history` control with an empty JSON body. This control removes unreferenced done/failed task records and terminal queue history; it does not pause autonomy. It is separate from Telegram conversation history, the event journal and deleting Git or OpenCode artifacts. There is currently no dedicated CLI or Coin tool for this action.

Cleanup retains every waiting/running/review task, tasks with surviving agent runs, workers referenced by retained integrators even while they wait without a run, and task records associated with the retained queue frontier. `queues.history_frontier` owns that frontier: queued work, blocked work awaiting recovery, records owned or proposed by retained tasks, and their transitive prerequisite/replacement/correction edges. The same set protects terminal tasks and queue records, preserving receipts, sessions, branch metadata and unfinished recovery work that those dependencies still need.

Repair Operators and their originating task/record remain protected while the same failure episode is current, including terminal repair attempts. Cleanup cannot erase that ownership and silently admit another repair; active Operators retain their origin evidence.

For removed task records, the daemon forgets disposable snapshots and lane residency. Git/worktree retirement remains a separate lifecycle operation; this button does not delete conversation files or branch artifacts. The reply reports task and queue removal counts. Active work and retained prerequisites may remain in the history lists after cleanup.

Evidence: `api.clear_task_history`, `queues.history_frontier`/`clear_history`, the dashboard click handler, README and `tests/test_halt.py`/`tests/test_queues.py`. Mechanism coverage includes transitive accepted prerequisites, blocked recovery artifacts and a waiting integrator's worker. A disposable native HTTP instance of the deployed code removed one unreferenced task and queue record, retained all four dependent/recovery task records unchanged in memory and on disk, and returned zero removals on a repeat request. The user's live task history was not cleared. Full dashboard execution against that live history remains unverified.
