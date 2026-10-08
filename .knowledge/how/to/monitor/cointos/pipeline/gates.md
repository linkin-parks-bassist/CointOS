---
status: green
revised_at: "2026-10-09T02:08:19+11:00"
checked_at: "2026-10-09T01:22:08+11:00"
expires_at: "2026-10-16T00:00:00+10:00"
---

The pipeline's mechanical checks are the dispatch-time `Relies on:` check, the packet check when an implementer finishes, and the landing gate's full suite (mechanism in `what/is/the/shape/of/cointos/work.md`). They are judged by whether they cut wasted cycles without stalling the pipeline. Run `cointos metrics --hours 72` (reads `~/.CointOS/state/events.jsonl` and its one rotated file; the header shows how many hours the journal actually covers, often about three days). For longer trends, record its output here at each review rather than relying on the bounded journal.

Baselines (Pigen only): 72 h ending 2026-10-02: 31 landings (test-contract 20, implementation 7, skeleton 3, integration 1), 70 worker items started, 11 manager recoveries, 0.35 recoveries per landing, implementation 23% of landings. 48 h ending 2026-10-06, under the former comparative implementation gate: 8 landings from 34 worker starts, 14 manager recoveries, no implementation landings. Failing packets wait to land with implementation; passing packets can land independently. 72 h ending 2026-10-09: 7 landings (implementation 2, skeleton 3, test-contract 2), 59 worker items started, 15 manager recoveries, 2.14 recoveries per landing, implementation 29% of landings, 6 infeasible briefs caught at dispatch, 4 packet test failures, 19 integrations, 53 complete and 7 blocked worker receipts.

Signals and what they mean:

- **Infeasible briefs > 0** means the dispatch check caught a false premise before any worker spent generation; each one is a saved worker run. Read `infeasible ...` lines: a false positive (the symbol exists under another spelling, or `Relies on:` named a test-only helper) means the manager guidance or check needs tightening.
- **Packet test failures** counts `packet tests failed` events: an implementer's finish refused because hidden tests failed. Repeated failures warrant inspecting the actual assertions and code: implementation errors, ambiguous briefs and tests beyond the contract require different remedies. Counts alone do not identify the cause.
- **Gate returns (implementation)** counts landings that broke a test passing on main and returned with it bundled in. These should be rare; a high rate means implementers are not running the existing suite before finishing.
- **Recoveries per landing** and **implementation share of landings** should improve on both baselines.

Failure modes to watch: landing timeouts (the full suite shares `timeouts.command_seconds`, 300 s, which a growing suite can outrun); test packets that never land because no implementation item depends on them; red tests left on main, which enforce nothing because a failure main already has never blocks a landing; and a decomposition manager loop on one item (one automatic pass, then alert).

Review again around 2026-10-16 with a fresh 72 h window and update this leaf's baselines.
