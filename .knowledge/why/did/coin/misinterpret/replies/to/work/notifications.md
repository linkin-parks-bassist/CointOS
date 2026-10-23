---
status: green
revised_at: "2026-10-23T19:16:35+11:00"
---

Work notifications used a separate Telegram sender that did not append accepted messages to Coin's conversation archive. Ordinary text replies reached Coin, but its prompt omitted the question the user had just received. A short reply therefore attached to an unrelated older topic. Durable intake also omitted Telegram's reply-to reference. Transport acceptance alone had been mistaken for a working conversational handoff.

The repaired design has one conversational egress for model replies. Every accepted outgoing part is archived under a file lock, including a first part when a later part fails. Delivery IDs are chat-scoped. Incoming text/captions, delivered notices and replies follow the agreed twenty/seven history scheme; internal wake instructions do not consume Telegram slots. Mid-turn outgoing messages reach the next model prompt.

Intake persists reply-to ID, text, time and bot provenance, retaining the referenced question after rollover. Outstanding delivered-notice evidence and durable explanation requests provide current context. Coin checks the owning task before interpreting an answer, applies authorised scoped controls and verifies the result. The Telegram and history owners define these contracts.

Internal reports remain evidence for a durable Coin explanation turn. The observer sends no canned attention notice. Work-update explanations use Coin priority; ordinary wakes remain background work. A durable explanation ID establishes handoff, not Telegram delivery. Questions explain context, actors, actions and consequences to a technical user unfamiliar with the code. Nonconsequential choices take the recommendation without asking.

Evidence: coin.py, coin_input.py, coin_notifications.py and test_progress_notifications.py. Native isolated probes exercised explanation of the correct topic and a user answer through the real hold-release API against a disposable queue. They do not certify arbitrary model judgment.
