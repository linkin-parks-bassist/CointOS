# Canonical contact bring-up — Astra, 2026-09-07

Authority: approved MVP contact plan C1-C5. Local inference only; David requests
economical local dispatch, five-minute polling and continued overnight work.
Root remains runtime/legacy-compatible until offline canonical composition and
approved reversible cutover are ready. Branch feat/mvp-contact at
/home/david/.worktrees/cointos-mvp-contact is the isolated staging owner.
Do NOT cherry-pick a half-converted schema into root. No service/Telegram/credential
or deployment authority follows merely from implementation permission.

Sieve read-only local-c1-contract-map confirms canonical interfaces absent; existing
cli.enqueue_task already owns explicit contract validation, atomic idempotency and
conflict refusal. conversation.append already owns source-id deduplication. Reuse
these owners; no second queue, parser or role-derived authority.

Astra qualifications to the map: its proposal to keep all old accept fields would
retain front/deep state, contrary to the clean canonical plan. New canonical records
must replace those fields, not establish a dual route. Its legacy exact-schema
claim based solely on initial accept fields is incomplete: later transitions add
fields. Inspect actual terminal shapes in the later conversion packet, not now.
Publication is C1/C3; delivery is only a gateway-observed fact, never inferred from
link_reply. Old consumers remain deployed only outside the staging branch until
C4 cutover; remove them from candidate active routes before contact acceptance.
These are implementation sequencing clarifications, not new lifecycle authority.

Bounded slices: shared canonical decision validator; canonical accept/claim/complete;
dispatch intent/idempotent enqueue composition; reply publication/source linkage;
separately bounded legacy conversion and caller/cutover closure. C2 reuses C1's
decision contract instead of creating an independent validator. No arbitrary new
schema fields or conversion semantics delegated to local judgment.
First packet local-c1-decision-validator is pure and additive: no runtime route
change, no C1-complete claim. Later packets remain subject to independent acceptance.
49f6136 pending correction: 15 tests pass, but code/tests confused nonblank with
nonempty; Astra independently found whitespace-only reply/task/role accepted.
local-c1-nonblank fixes this existing contract, preserving original string content.
Correction 60a6970 accepted in staging with 49f6136: Astra passed 16 focused tests
and reviewed exact diff. No root source integration. Next local-c1-accept-claim
stages schema2 accept and exclusive durable claim; existing legacy route tests
will intentionally expose candidate cutover incompleteness. Report these honestly,
do not weaken tests or deploy the staged branch. Completion/dispatch/link/conversion
are separate next packets; C1 and full contact remain incomplete.
e1b0acd accepted in staging: Astra reviewed diff/tests and independently passed
12 canonical tests. schema2 uses only canonical fields, duplicate legacy refusal,
per-turn locked claim and no-write repeat refusal. Worker honestly reports old
test_control_turns: 11 run, 8 failures + 1 error, 2 pass; no old tests modified.
Those are candidate C4 route-removal/composition blockers, not runtime regressions
in root. Next local-c1-complete-decision adds only durable completion/replay.
a268b91 accepted in staging: Astra independently passed 18 canonical tests and
reviewed completion copy/immutability/no-write replay. Next local-c1-dispatch-intent
only reserves the exact validated task contract and turn-scoped key. The existing
A1 enqueue owner retains workspace/authority admission; later dispatch composition
must use it and never infer permissions from model role. Plan's old example lacks
the now-required requirements field; use current A1 fixture/validator, not a weaker
local substitute. No source changes cherry-picked to runtime root.
