---
status: green
revised_at: "2026-11-18T21:13:21+11:00"
---

Coin keeps ongoing instructions outside rolling chat history. For an ongoing photo destination, use attachment_route once: a durable per-user filesystem rule handles arriving captionless photos without model turns, expected totals or repeated counting. It survives quiet batches and restarts until changed or stopped. The attachment owner defines registration catch-up, captions, errors and receipts.

For other explicit unfinished requests, retain_request(instruction) stores scope and completion condition privately under state/coin-<identity>/requests, deriving user/chat identity from transport. Identical registration (same user and stripped text) is idempotent. Active instructions are refreshed each round independently of 20-to-13 history rollover. finish_request(id) retires only that user's request after completion or cancellation. Corrections supersede old instructions. A quiet queue or completed batch does not establish completion.

Stored registry keys are opaque. Retained requests and result reports name new entries by content hash, but reads only require the key to equal the stored id (reports: a nonempty key) and deduplicate by matching fields, never by recomputing the hash. Coin reads both registries before every turn, so a recomputing validator turns any stored-text change into a silent outage: when the work directory was renamed to ~/Work, paths inside Professional's state were rewritten while their content-derived keys were not, and every Professional turn failed with `invalid retained instruction` / `invalid result report` until keys became opaque. tests.test_coin_requests and tests.test_coin_reports cover stale-key entries staying readable, finishable and deduplicated.

Records preserve instructions, not extra authority, facts or evidence of effects. Maintained knowledge belongs in knowledge trees and future observations use wakes. Ordinary low-stakes copying/moving should trust a successful operation; extra verification is warranted by an actual error, collision or explicit request, not the size of the upload.

The cancelled AOW photo job has no active retained request or watcher. All 284 received photo receipts were settled to the requested folder; the earlier expected 294 is not a continuing quota. Initial model registration/fidelity for general retained requests remains an acceptance limit. tests.test_coin_requests covers persistence, user isolation and round refresh; tests.test_coin_routing covers ongoing photo rules independently of model context. The delivery evidence owner records the closed transfer.
