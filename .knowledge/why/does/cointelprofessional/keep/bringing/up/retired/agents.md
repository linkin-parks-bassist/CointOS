---
status: green
revised_at: "2026-09-26T08:21:20+10:00"
---

Cointelprofessional kept volunteering a retired agent's name after that agent's jobs were terminal. Two context sources feed it back:

1. **Status payload.** `ecosystem/facts.py::lifecycle()` returns `latest_by_role` and `recent_agents` across all job states, including terminal history. The model conflated historical records with active work. `ecosystem/control_runtime.py::_prompt_lifecycle_facts()` now filters both fields to active states (`queued`, `ready`, `claimed`, `runner_starting`, `running`, `awaiting_verification`) before they reach the prompt. `ecosystem/queries.py` `last_role_spawn` still reads unfiltered history, which is correct for an explicitly historical question.

2. **Conversation history.** `ecosystem/conversation.py::recent()` replays the last 20 messages (12,000 characters) of `state/conversations/telegram-<user>.jsonl` into every control turn. Once the name dominates recent turns, including turns where the model explains why it keeps mentioning the name, the replay is self-perpetuating even with a clean status payload. Removing a retired name from live behaviour requires scrubbing or truncating that conversation file, not just terminalizing jobs.

Current/status-facing facts must distinguish active work from terminal history structurally; expose history only through an explicitly historical query.
