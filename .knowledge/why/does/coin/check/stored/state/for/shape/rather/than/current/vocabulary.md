---
status: green
revised_at: "2026-11-18T21:46:15+11:00"
---

Coin reads its private registries (inputs, retained requests, result reports, follow-ups, wakes) before or during every turn, and each read validates the whole file. A read-time check that recomputes derived values or demands today's vocabulary therefore turns harmless drift into a total, silent outage: one renamed path, task id, role, state name, keyword or tzdata zone disables every turn or every wake for that identity. A work-directory rename did exactly this to Cointel Professional for about a day.

The rule:

- Registration and new writes check current vocabulary (roles in schema.KINDS, unit/task states, resolvable timezones, Telegram media kinds, content-derived keys).
- Stored records are checked for shape and internal consistency only. Keys and ids are opaque; deduplication compares the actual fields, never a recomputed hash. Recorded fields such as an input's `kind` are trusted, not re-derived. Stored wake roles, states, outcome names and timezones are not checked against current lists. A stored event may claim `observed` only for a due/matched outcome, which keeps forged observations refused.
- A record that cannot be evaluated is isolated, not fatal. `wakeups.ready` logs and skips any per-record failure, and listing reports a removed timezone as `problem` with no `next_run`. Dispatch refuses a retired agent role and tells the user.
- A failing turn must not be silent. After the same error repeats three times, `coin.notify_failure` sends the user one notice per error per process, with the bot token redacted. Retries and retained inputs continue as before.

Whole-file refusal remains right for genuine corruption: wrong top-level shape, duplicate fields, non-finite numbers, unsafe or non-private storage, mismatched ids, unknown condition kinds.

tests.test_stored_state_tolerance covers each case. tests.test_coin_requests and tests.test_coin_reports cover stale keys, and tests.test_coin_wakeups keeps the corruption refusals.
