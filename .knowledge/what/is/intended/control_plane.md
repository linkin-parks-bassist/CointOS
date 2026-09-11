---
verified_at: '2026-09-11T18:43:14+10:00'
verified_by: codex /root
scope: project local
source: docs/specs/2026-09-05-cointos-mvp-design.md; docs/decisions/0013-preserve-pre-mvp-contact-history.md; docs/status.md
verification: Reconciled durable design documents with current status; no live deployment claim made.
review_when: Recheck when contact, messaging, or control-plane implementation changes.
---

`Cointelprofessional` is the permanent Telegram-facing control-plane identity. It
should respond naturally and promptly with recent conversational context, remain
truthful about capabilities and completion, and escalate deeper work without canned
customer-service phrasing. Intended agent messaging is durable, directly addressed,
transport-independent, and eventually visible at safe boundaries during live runs.
Design intent does not establish current deployment or service health; consult
`where/is/runtime_truth.md` for that.
