# 0014 — Contact lifecycle and front admission

2026-09-07. David explicitly approved recommendations 1 and 2. Astra records.

Use new/open/closed message state, four entry outcomes (respond, escalate,
respond+escalate, ignore), and linked context across states. Escalation includes
deeper reasoning without an actionable task. Final reply durable publication permits
closure; Telegram delivery is separate. Waiting/retryable deep failures stay open.

Use an ephemeral gated credential-bearing process per front inference call under
real R1/R3 admission and conservative verified close. This approves the design,
not service activation, live cutover, or fabricated termination. R4-PRECISE in
decision0012 remains a required successor.

The entry model and decision policy must remain tunable through real-world use.
Prefer competent, responsive handling with ready escalation when needed; natural
contextual ACKs, not canned instant replies or fake substantive answers. Trivial
authorized information fetches and intentional silence remain valid. Do not force
every message through deeper reasoning. No policy choice grants new tool authority.

Approved staging spec: docs/superpowers/specs/2026-09-07-message-lifecycle-design.md
in /home/david/.worktrees/cointos-mvp-contact. Front-admission decomposition:
agent_notes/0020-front-admission-options.md in that worktree. Code and live evidence
remain outstanding; automatic goal continuations were not used as approval.

David's subsequent refinement: silent escalation mandates a prompt response from
the escalation model. If significant work follows, it sends an initial contextual
response and later a separate follow-up. The intermediate response is not final
completion and must not close the message; distinct replay-safe publication and
timing/admission tests are required in the deep-response integration. No numerical
response deadline has yet been specified. Silence is not authorization to queue
unacknowledged work indefinitely.
