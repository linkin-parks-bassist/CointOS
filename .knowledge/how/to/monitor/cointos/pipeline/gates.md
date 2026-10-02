---
status: green
revised_at: "2026-10-02T18:52:55+10:00"
expires_at: "2026-10-09T00:00:00+10:00"
---

The two mechanical test-contract gates (dispatch-time `Relies on:` check and landing-time red gate; mechanism in `what/is/the/shape/of/cointos/work.md`) are judged by whether they cut wasted test-contract cycles without stalling the pipeline. Run `cointos metrics --hours 72` (reads `~/.CointOS/state/events.jsonl` and its one rotated file; the header shows how many hours the journal actually covers, often about three days). For longer trends, record its output here at each review rather than relying on the bounded journal.

Baseline before installation (72 h ending 2026-10-02, Pigen only): 31 landings (test-contract 20, implementation 7, skeleton 3, integration 1); 70 worker items started; 11 manager recoveries; 61 complete and 5 blocked worker receipts; 0.35 recoveries per landing; implementation 23% of landings. Earlier failures this targets: storage-matrix-instances (12b) and the section-8 boundary contract were planned against owner APIs that did not exist, each costing a worker run plus a manager pass.

Signals and what they mean:

- **Infeasible briefs > 0** means the dispatch check caught a false premise before any worker spent generation; each one is a saved worker run. Read `infeasible ...` lines: a false positive (the symbol exists but under another spelling, or `Relies on:` named a test-only helper) means the manager guidance or check needs tightening.
- **Gate returns (test-contract)** counts landings returned for a missing/mismatched `Expected red`, a passing red, or a regression. A few early returns are expected while workers learn the line format. The rate should fall within a day; a persistently high rate means the worker prompt format is unclear to Qwen. Inspect `landing gate rejected` events (`reason` field).
- **Recoveries per landing** should fall below the 0.35 baseline as infeasible briefs stop reaching workers.
- **Implementation share of landings** should rise above 23% once test-contract chains stop being redone.
- **Red gate** line: declared reds verified per test contract; zero across many landings means workers write `Expected red: none` to dodge the gate, which the integrator should challenge.

Failure modes to watch: landing timeouts (all contract commands share `timeouts.command_seconds`, 300 s); test-contract work stalling because managers cannot produce a valid `Relies on:` line (visible as repeated queue refusals in manager transcripts); and a decomposition manager loop on one item (one automatic pass, then alert).

Review again around 2026-10-09 with a fresh 72 h window. Keep or revert each gate based on these numbers, and update this leaf's baseline.
