# Overnight review and local dispatch handoff

Recorded by Astra (Codex `/root`), 2026-09-06. Personal CointOS scope.
Reviewed base: `2d754f2`; overnight comparison starts at `b0d4de7`.
David requests local Qwen dispatch for nearly all implementation and inspection,
with Astra retaining judgment and acceptance while minimizing hosted tokens.

## Evidence and acceptance boundary

The initial checkout was clean. Fresh `python3 -m unittest discover -s tests -q`
passed 501 tests in 17.834 seconds; `git diff --check` passed. This is a coarse
review with targeted inspection, not independent acceptance of every overnight
milestone. No production code or service was changed by this review.

Two concrete A2 findings are deferred hardening, not MVP bring-up blockers
(David's correction and explicit continuation approval, 2026-09-06):

- `ecosystem/evidence.py:51`: `_page_boundary` removes trailing continuation
  bytes even when the final UTF-8 character is complete. Calling `_page` with
  the exact encoded length of any of `é`, `€`, `😀`, or `abc€` raises
  `ValueError: evidence is not valid UTF-8`. The existing test cuts an incomplete
  character, then ends the next page in ASCII, missing this case.
- `ecosystem/evidence.py:122`: every page reads the entire source into memory
  before applying the limits, even when the remaining byte/item budget is zero.
  The output envelope therefore does not bound memory allocation. Whole-file
  digest semantics also imply full-file I/O; distinguish that cost explicitly
  from the output budget rather than claiming fully bounded inspection.

Architectural assessment of this slice: scope validation and explicit page
records provide useful vertical contracts, and ordinary functions share the
scope representation directly across horizontal modules. The UTF-8 fingertip
violates its encoding contract; resource limits currently describe output but
omit material input costs. These faults belong in the evidence owner. The
operator-session launch cleanup path merits a separate review; not yet verified.

## Deferred local worker packets, sequential ownership

Both workers must read the workspace/repository instructions and manifesto.
Neither packet authorizes live service/model changes, publication, credentials,
other projects, or writes to runtime records. Register admission and isolate the
writer before launch. Local build chunks have item/output budgets, not an imposed
wall-clock kill. Return a compact handoff (at most 30 lines), focused command
results, and an exact diff; stop at acceptance or a named blocker.

1. `a2_utf8_repair`, assigned name `Sieve`: base `2d754f2`; read/write only
   `ecosystem/evidence.py` and `tests/test_mvp_evidence.py`. Deliver one regression
   repair for complete trailing 2/3/4-byte characters. Preserve incomplete-tail
   truncation and rejection of cursors inside a character. Cover exact-boundary,
   partial-boundary and multi-page reconstruction with plain-function tests;
   ensure the existing unittest collector includes them. Show failing tests
   before repair and passing focused evidence tests afterward. No API changes.
2. `a2_input_resource_review`, assigned name `Sift`: after packet 1, read only
   those two files and the A2 section of the autonomy plan. Deliver at most two
   concrete options for limiting memory while preserving whole-file digests,
   identifying remaining I/O cost and behavior for changing files. No code edits;
   Astra must settle the resource contract before implementation.

## Dispatch prerequisite observed, not repaired

Local health on this review showed only pinned `Qwen3.5-4B-GGUF` loaded and idle;
Qwen3.8 was not loaded. Available host memory was about 114 GiB, but this alone is
not resource admission. Port 13305 was listening; configured proxy port 13306 was
not. `agent-inference-proxy.service` and `agent-resource-guard.service` reported
inactive; `agent-telegram.service` reported active (not end-to-end contact proof).

`state/resource-control.json` still records `mode: emergency` and a failed
sole-survivor context escalation from September 4. Its boot ID differs from the
current boot. `workload_control.admission_reasons` rejects non-normal resource
mode. Do not infer permission to discard that latch from its age or start a
direct backend worker around the admitted path. No local worker was launched.

David explicitly approved reconciling containment and restoring local dispatch.
He prioritizes an existing, somewhat stable MVP before exhaustive auditing.
The immediate review checks spec/plan fidelity, weakened tests, and unsupported
completion claims; edge-case hardening must not displace bring-up.

Next coordinator deliverable: reconcile the local build admission route and
establish a registered Qwen run while preserving Coin. Live changes must follow
the existing approval/activation boundary; a stale emergency record is evidence
to investigate, not evidence of recovery. A3 also needs H1; its mention as next
in execution memory does not make its prerequisites complete.

## Plan-fidelity pass after David's steering

Targeted inspection of the overnight test diff found fixture upgrades for the
accepted scheduling snapshot, preserved preemption assertions, and replacement
of one old scheduler test with configured-band/fairness tests. The inspected
changes do not show deliberate test suppression. This does not establish motive
or validate every changed test. The fresh 501-test result is reproducible.

R5 is not fully integrated as claimed: its plan explicitly requires cumulative
task budget and says rollover is not an attempt failure. `_run_preemptibly`
initializes fresh usage from attempts at each launch, returns no usage on normal
completion or preemption, and only saves `budget_usage` on budget exhaustion.
`execute_next` increments attempts at every runner launch. No executor path
decrements remaining time/output budgets. The arithmetic helper tests therefore
do not prove the stated cumulative executor behavior. Repair this integration
before claiming R5/R6 acceptance; scope is executor accounting plus focused
continuation/composition tests, not a broader budget redesign.

R4's production HTTP adapter still passes `observe=None`; normal release remains
unverified and the runner closes into reconciliation-required. Earlier independent
adjudication explicitly identified this missing backend observer. R8/R5/R6 notes
disclose this live prerequisite, but their unqualified 'complete' labels overstate
integrated readiness. Preserve the useful code and distinguish offline task
progress from missing production acceptance.

The live registry lacks the metadata fields expected by `models.snapshot`; all
routes currently defer. This prerequisite predates the overnight changes. At this
boot the measured GTT total is 64 GiB, while configuration permits up to 100 GiB;
the measured lesser limit is authoritative. A trusted metadata adapter is needed,
not invented fields or a production admission bypass.

While Astra prepared bootstrap, another OpenCode process (PID 16142, cwd
`/home/david`) loaded Qwen3.8 at 131072 context and began inference. The bootstrap
script's fresh memory check stopped before policy publication, model loading or
resource-state modification. Ownership/scope clarification is pending from David;
no process belonging to that session was interrupted.

## Authorized bring-up execution checkpoint

After David cleared his Qwen session and said to proceed, Astra restored the
pinned control model, loaded Qwen3.8 at 131072 context, published the validated
scheduling snapshot, and started transient `cointos-mvp-proxy.service`. The old
emergency state was saved before explicit operator recovery; no survivor success
was fabricated and old runtime JSONL was not rewritten.

An operator observation packet qualified the already loaded allocations using
the real backend `/v1/models` metadata (`n_params`, `size`, `n_ctx_train`),
`/props` tool support/slot count, and Lemonade's exact launch/health records.
Only the observed allocation was qualified as a context quantum. It passed the
existing R1/R3/R4 admission path. This is commissioning evidence, not the missing
production metadata adapter.

The first local packet `local-r5-continuity-repair` was too broad. It consumed a
large context, compacted before any edit, and ended on `reason: length` at the
coordinator's 8192-token reply limit. OpenCode returned zero but produced no
patch, regression test, or final repair handoff. Astra rejected the attempt;
there was no worker claim of a completed repair. Do not equate this harness exit
with semantic completion or describe it as evidence of lying.

The stopped packet was independently reconciled using process/group absence,
zero proxy in-flight claims, and exhaustive idle slots from the allocated
backend. The operator-commissioned backend observer supplied `reconciled_absent`
to R3 with its exact lease binding and saved evidence; R1 reached quiescence.
The old credential was closed to new calls; no normal-end evidence was invented.
Detailed commissioning records/scripts remain in the ignored SDD ledger.

Retry `local-r5-active-quota-repair` narrows delivery to the immediate active-run
quota fault: attempts==maximum_attempts must not stop the permitted current
attempt, and maximum_children=0 must not prevent the parent itself running.
The first retry exposed OpenCode's installed 32000-token ceiling: reserving
32768 caused an honest proxy rejection before inference. The corrected `-v2`
packet matched that exact client ceiling. The two temporary coordinator-owned
AGENTS.md files were removed before integration.
Cumulative time/output accounting remains a separately named unfinished task.

The narrowed worker delivered `6969e4b`, integrated by Astra as `99170fb` after
review. Its real-child regression and quota-owner tests failed on the old code;
focused checks then passed 10+4, and the complete suite passed 504 tests. Astra
independently reran the 14 focused tests successfully. Only the budget owner,
two test files, and its handoff note changed. No test assertions were removed,
no spec text was relaxed, and the handoff explicitly leaves cumulative accounting
and backend-close integration unfinished. The worker exited, the backend was
observed idle, and its R1/R3 leases were reconciled before integration. No push.

Next independently verifiable implementation packet: cumulative observed task
time/output across two runner rounds, preserving per-run time and zero-cost
waits. Keep its evidence to the exact accounting/return/persistence functions and
a small composition fixture. Retain the original contract allowance when testing
cumulative usage; never compare cumulative usage with an already depleted quota.
Production metadata and backend-close observation remain distinct bring-up tasks.

## Accepted cumulative-usage repair (2026-09-06)

Local packet `local-r5-cumulative-usage` delivered `adc13c1`, integrated as
`d113c2a`: executor accounting/persistence only, four function-style regressions,
and a short handoff. No old assertions or contract limits weakened. Red evidence
was three missing-parameter errors and one missing persisted-usage error; green
was 4 new / 18 focused / 508 full tests. Astra independently ran the focused and
full suites and probed carried output exhaustion plus wrap-up bytes/time.
The output/time allowance is not decremented again by this repair. Attempts still
increment per launch; retry/rollover semantics remain a separate unfinished item.

Worker exploration exceeded the targeted-read preference and required two
coordinator-owned nested AGENTS checkpoints; those were removed after stopping.
It initially hid the full-suite summary with tail, noticed this itself, and reran
with captured Ran/OK evidence. After its committed final handoff OpenCode started
another step. Astra cancelled proxy admission and sent identity-checked SIGINT
at the deliverable boundary (exit -2, not a worker failure claim). Actual process
and backend absence were observed, leases reconciled, and the reviewed artifact
accepted independently of exit status. Append-only transcript and absence evidence
remain in the ignored build ledger. No push or broader service activation.
