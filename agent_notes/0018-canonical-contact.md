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
48150a9 accepted in staging: Astra independently passed 21 canonical tests and
reviewed exact intent/key/copy/no-write replay contract. Next local-c1-dispatch-once
composes with existing A1 enqueue and requires a real temporary-filesystem test of
job-created / turn-finalization-failed replay. Intent durability alone is not yet
one-job composition proof; no executable contact acceptance claimed.
cc52633 accepted in staging: Astra independently passed 33 focused tests including
REAL A1 job creation followed by injected final turn-write failure, then replay to
same job with exactly one job file. Conflicting concurrent finalization is refused;
enqueue occurs outside turn lock using durable facts. No rollback deletes a job.

Next local-c1-reply-link is only publication linkage. Per C3's separate semantic
identities and its decision-only inbox acknowledgement, top reply_state describes
the substantive decision, not an aggregate over task results. reply_links keeps
decision/task_result ids and publication timestamps; a later task result must not
regress an already-delivered or unknown decision. Gateway/outbox delivery records
remain the authority. link_reply does not send or append conversation history;
those owners compose in C3. Canonical ids are telegram-N:decision/:task_result.
edd341b accepted in staging: Astra reviewed source/tests and passed 27 contact
tests. Independent late-result probe confirms first task_result linkage preserves
already delivered and delivery_unknown substantive states. No outbox/send effect.
Next local-c1-legacy-shapes is READ ONLY: establish actual terminal legacy shapes
and missing historical facts before assigning conversion semantics. Do not invent
a past respond/dispatch decision or job simply to make old records fit schema2.

## Parked conversion semantics and next C2 seam

Sieve local-c1-legacy-shapes confirms old terminal front/deep/followup shapes;
Astra checked actual control_worker: only followup/actions, not a canonical
respond/dispatch decision, are persisted. A schema2 completed model decision cannot
be reconstructed honestly. Conversion remains OPEN pending explicit historical
representation choice; do not invent decisions/jobs or silently auto-migrate.
Candidate alternatives to present before implementing: immutable historical
envelope with preserved original plus replay fence, or separately preserved terminal
archive with canonical terminal identity references. No choice or migration made.
Nonterminal old work must still be previewed/drained before any conversion.

C2 seam found by Astra: inference.request is currently a low-level admitted client
requiring lease+32-byte credential, whereas the C2 plan's plain mocked call omits
that production setup. local-c2-admission-map is read-only evidence for reusing
the actual R4 owners. Do not mistake a fake infer callback for reserved front
acceptance, manufacture credentials or introduce direct HTTP. C2 pure prompt/status
work may stage independently once its input contract is explicit; live integration
must close the real admission seam first.
Sieve admission map finds no high-level admitted helper. Astra confirmed ordinary
executor explicitly refuses front. Map qualifications: OpenCode uses its configured
proxy HTTP client, not ecosystem.inference.request; same-process R1 registration
does NOT establish a safe close while that process remains alive. Do not accept
the map's proposed acquire/self-register/release sequence as verified architecture.
Map did not inspect reserve_sequence body, so exclusive front admission proof is
still open. Its operator-session/new-wrapper fork is unresolved, not permission to
borrow David's operator owner for Coin. Park executable C2 wiring pending exact
owner/close contract; continue independent approved pure prompt in
local-c2-decision-prompt without fake admission or decide stub.
Astra inspected the omitted owner code: _validate_sequence_request enforces Coin
authority and configured front proxy; reserve_sequence selects only reserved front
indices, and resource_envelope refuses an exhausted/None sequence. Thus logical
front exclusion exists. completed_run_termination explicitly requires the bound
process ended, confirming same-process long-lived worker closure is NOT supplied.
This is a missing front request lifecycle composition, not permission to weaken
release proof or claim logical reservation proves native physical-slot correlation.
R4-PRECISE remains the latter's required successor.
685cecf accepted in staging: Astra independently passed 10 prompt/decision tests
and reviewed source. Pure prompt preserves supplied facts/history, uses one C1
validator, invents no actions, has NO decide/inference/status-read implementation.
C2 status adapter not yet implemented; no existing status/health module found by
bounded filename check, so no factual projection is assumed. Next independent
local-c3-publication-map is read-only preparation of approved immutable ordinary
spool publication; full C3 still depends on C2, and no active egress changes occur.
Sieve local-c3-publication-map identifies reusable records._create_exclusive_json
(fsynced private file, link publication, collision raises) and validated full
telegram_api.read_inbox_entry. Correction: source_key is telegram-N:kind, NOT just
inbound id as map proposed. C3 examples and C1 link use distinct decision/result
identities. Next local-c3-intent-link stages strict seven-field ordinary intent
validation and read-only authenticated inbox linkage. No publisher/sender yet;
shared-directory ownership remains C4 packaging, not silently enabled in tests.
f57757c reviewed: Astra independently passed 75 ordinary/gateway/records tests;
link validates before path use and checks actual inbox payload identity. One small
contract gap: kind list/dict currently leaks TypeError. local-c3-publish-intent
must correct that guard/table while adding immutable ordinary publication, then
accept the two together. Publication will read trusted inbox before writing and
preserve original created_at/bytes on same semantic replay; no gateway delivery or
critical mutation, and user directory provisioning remains C4.
b3f5b41 accepted with f57757c in staging: Astra reviewed code and independently
passed 78 ordinary/gateway/records tests. Publisher validates trusted inbox first,
uses existing exclusive writer, preserves timestamp/bytes/inode on replay, rejects
conflicts without repair, and fixes kind type guard. Test sentinel was placed at
root/critical, not actual outbox/critical; Astra independently probed actual path
and gateway absence successfully. local-c3-publication-replay-test corrects that
fixture path and adds two real temporary-filesystem C1/C3 composition proofs,
including publish-success/link-failure recovery. No production worker implied.
Astra full staging discovery at b3f5b41: 627 run, 9 failures + 1 error. Nine are
the already recorded test_control_turns old-route cases; the additional failure is
test_notifier.test_terminal_result_uses_notifier_without_blocking_telegram_ingress,
which still invokes legacy telegram.accept_update and expects a front reply.
Independent focused rerun confirms failure at that old-route sent-list assertion,
not ordinary publisher behavior. C3 notifier/C4 canonical caller closure must
replace that obsolete route and retain notification/delivery invariants. Do not
skip or weaken tests to call this candidate deployable. Root source remains green
at its separate 622-test accepted checkpoint.
The same b3f5b41 staging checkpoint separately passed all 33 integration tests.
e85ee89 tests accepted: Astra reviewed both real-root composition tests and passed
17 focused tests; sentinel now actually outbox/critical. Publish/link failure
replay remains byte/inode stable and result-before-decision does not fabricate
delivery or duplicate jobs. Test-only change, not production contact acceptance.
Next local-c3-egress-map is read-only decomposition of approved gateway ordinary
send/degraded-notice identity separation; no live gateway modifications.
Sieve egress map confirms old degraded send mutates inbox egress_state and no
ordinary per-identity delivery owner/flock exists. Astra checked gateway and record
helpers. Corrections: C3 can reuse existing inbox egress_state for decision-only
acknowledgement; no second ack field is required. Kernel flock releases on process
exit; don't invent a persistent lock-owner/stale-healing protocol. Legacy inbox
meaning conversion remains a C4 cutover concern, not an implicit runtime fallback.
Next local-c3-delivery-records stages only exact gateway/ordinary-delivery records
for decision/task_result/degraded-notice with monotonic states. Attempt evidence
and per-inbound serialization must follow BEFORE any sender is wired. Existing
critical protocol remains untouched; no new gateway activation authority inferred.
