---
status: green
revised_at: "2026-10-17T21:16:53+11:00"
---

The installed daemon owns live planning/control commands in ~/.CointOS/state/cointos.json. This source checkout is not a live command-queue projection.

Use cointos jobs --project PROJECT and cointos task PROJECT:ITEM to inspect command ownership, handoffs and completion. Submit changes through the daemon API. Runtime-generated knowledge projects the ledger; it cannot independently accept or replace work.

The status wanted line counts open items, unheld blocked items, and blocked items with or without a recovery owner or runnable continuation. Absence of recovery is not evidence that the user owes a product decision. CLI source labels the unowned remainder without recovery/continuation; Coin must inspect the exact cause and authority before asking for a decision. A failed planning/controller run may have valid live children while remaining unaccepted itself.

Test fixtures publish into disposable knowledge roots/registries. An empty fixture queue says nothing about live work.
