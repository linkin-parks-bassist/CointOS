# CointOS MVP Coin Approval and Release Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans for the assigned task only.

**Goal:** Turn a verified autonomous improvement into an explicit Coin approval request and a recoverable activation.

**Architecture:** Candidate work is isolated from live imports. Verification and authenticated approval bind one immutable manifest. A fixed installed release manager drains workers, switches a release, checks health and restores the prior release on failure.

**Tech Stack:** Git worktrees, Python standard library, content-addressed local release directories, JSON records, systemd, existing Telegram gateway.

**Spec:** [MVP design](../specs/2026-09-05-cointos-mvp-design.md).

## Global constraints

- David explicitly requested approval via Cointelprofessional after tests/review.
- Preparing candidates is permitted within the task; activating any changed candidate requires that approval.
- No approval is inferred from model prose, silence, an old request, or elapsed time.
- Coin stays available; no OOM; seamless context handovers remain mandatory throughout activation.
- Root performs fixed installed file/service operations, never a candidate-supplied shell/build/install script.
- Logs remain append-only. Source and runtime paths are distinct. Never modify the live source checkout from an agent candidate.
- Read the [swarm contract](2026-09-05-cointos-mvp-swarm.md); use its test collector and ownership rules.

## P1 — Isolated candidates and exact verification evidence

**Owner/budget:** Sol medium, 20 minutes. Local child: digest validation or a manifest test, <=300 seconds.
**Depends on:** A1, R1. Runs before A4; does not depend on contribution processing.
**Files:** create `ecosystem/candidates.py`, `tests/test_mvp_candidates.py`; modify
`ecosystem/executor.py`, `ecosystem/verification.py`, `config/workspaces.json`.
**Interfaces:** `create_candidate(root: Path, job: dict, base_revision: str) -> dict`;
`seal_candidate(candidate: dict, tree_digest: str, changed_paths: list[str], checks: list[dict]) -> dict`;
`candidate_binding(candidate: dict) -> str`; `candidate_verified(candidate: dict, verdict: dict) -> bool`.
Manifest fields: `schema_version`, `candidate_id`, `job_id`, `workspace`, `base_revision`,
`base_release_digest`, `tree_digest`, `changed_paths`, `target_class: user|survival`,
`target_units`, `checks`, `checks_digest`, `verification_digest`, `state`.
`candidate_binding` hashes schema version, candidate/job identity, source base revision,
base-release digest, tree digest, canonical changed-path/target lists, target class and
check-evidence digest. Mutable lifecycle state is excluded. The verifier independently
observes that whole binding; altered targets or check evidence invalidate verification.

- [ ] Write exact-digest verification and live-workspace rejection tests:

```python
from ecosystem.candidates import candidate_binding, candidate_verified

def test_changed_targets_invalidate_otherwise_valid_verification():
    candidate = {"schema_version": 1, "candidate_id": "c1", "job_id": "j1",
                 "workspace": "/candidate", "base_revision": "b" * 40,
                 "base_release_digest": "c" * 64, "tree_digest": "a" * 64,
                 "changed_paths": ["ecosystem/evidence.py"], "target_class": "user",
                 "target_units": ["agent-ecosystem.service"],
                 "checks": [{"status": "pass"}], "checks_digest": "d" * 64,
                 "verification_digest": None, "state": "sealed"}
    verdict = {"accepted": True, "candidate_id": "c1",
               "verification_digest": candidate_binding(candidate)}
    assert candidate_verified(candidate, verdict) is True
    altered = {**candidate, "target_class": "survival",
               "target_units": ["cointelprofessional-gateway.service"]}
    assert candidate_verified(altered, verdict) is False
```

- [ ] Run `python3 -m unittest discover -s tests -p 'test_mvp_candidates.py' -v`.
- [ ] Create a dedicated worktree per writer from the coordinator's reviewed source snapshot;
  record the exact base and path. Give the worker only its write scope and output directory.
  Read-only roles receive no code-write grant. Runtime/import paths are excluded from write scopes.
  Where process filesystem restrictions are used, verify they actually reject a write outside
  the candidate; do not mistake an OpenCode prompt for containment.
- [ ] Seal candidate data after focused checks and independent verification. Hash file bytes,
  executable modes and relative paths in deterministic order. Reject symlinks escaping the
  allowed tree and unlisted files; no credentials or runtime state in release content.

```python
verified = (verdict.get("accepted") is True
            and verdict.get("candidate_id") == candidate["candidate_id"]
            and verdict.get("verification_digest") == candidate_binding(candidate))
```

  The verifier obtains its own observed digest; it does not merely echo the producer's claim.
  Use current verifier plus this binding, not a second review subsystem.
- [ ] Test candidate modification after verification, contaminated worktree, missing artifact,
  and one valid sealed candidate with actual temporary files. Commit only named files.
**Acceptance/stop:** candidate edits cannot affect running services; evidence refers to exact bytes.

## P2 — Authenticated, durable approval through Coin

**Owner/budget:** Sol medium, 20 minutes. Local child: parser/replay tests, <=300 seconds.
**Depends on:** P1, C3; uses C3 gateway egress and authenticated accepted-update identity.
**Files:** create `survival/approvals.py`, `ecosystem/approval_requests.py`,
`tests/test_mvp_approvals.py`; modify `survival/gateway.py`, installed approval spool permissions,
`roles/_control-plane.md`.
**Interfaces:** `parse_approval(text: str) -> tuple[str, str] | None`;
`request_approval(candidate: dict, now: float, lifetime_seconds: float) -> dict`;
`accept_approval(request: dict, accepted_update: dict, observed: dict, now: float) -> dict`.
`observed` contains independently observed `candidate_binding`, `tree_digest`,
`active_base_digest`, `target_class`, canonical `target_units` and `boot_id`.
Acceptance compares every bound value; P3 repeats this check immediately before switching.
Approval request contains candidate digest, base release, allowed targets, expiration, request ID
and verification reference. Gateway chooses the authenticated destination from accepted
configuration, not from model output. Only gateway-owned acceptance can authorize activation.

- [ ] Test exact grammar and altered-candidate refusal:

```python
from survival.approvals import parse_approval

def test_literal_approval_is_unambiguous():
    assert parse_approval("APPROVE approval-0123456789abcdef") == (
        "approve", "approval-0123456789abcdef")
    assert parse_approval("maybe APPROVE approval-0123456789abcdef") is None
    assert parse_approval("approve approval-0123456789abcdef") is None
```

- [ ] Run `python3 -m unittest discover -s tests -p 'test_mvp_approvals.py' -v`.
- [ ] Use exact `APPROVE approval-<16 lowercase hex>` and `REJECT approval-<16 lowercase hex>`
  bodies. All near-matches remain ordinary text. The local immutable request stores the full
  256-bit candidate digest; a short ID is an identifier, not authentication. Persist incoming
  update identity before recording approval. Replaying the same update cannot create a second
  activation or renew an expired approval.

```python
bound_fields = ("candidate_binding", "tree_digest", "active_base_digest", "target_class", "target_units", "boot_id")
if now >= request["expires_monotonic"] or any(observed[key] != request[key] for key in bound_fields):
    return {"state": "reapproval_required", "request_id": request["request_id"]}
```

  Expiration is boot-bound; after reboot an unconsumed request needs a fresh request unless
  its persisted trusted expiration representation can be independently validated. Initial
  lifetime is 86400 seconds through central timing policy. Candidate/base/targets are immutable.
- [ ] Render one concise request: purpose, changed scope, checks, independent verdict, expected
  effect, rollback and literal approval command. Rejection is terminal for that request.
  Status questions can inspect pending requests without changing them. Send failure/unknown
  delivery remains distinct from approval; no repeated unsolicited approval messages.
- [ ] Test unauthorized update, expiry, wrong boot, wrong tree/base, repeated approve/reject,
  and gateway receipt while inference is stopped using fake Telegram. Commit named files.
**Acceptance/stop:** only David's authenticated exact approval for current bytes permits activation.

## P3 — Fixed release activation and recovery owner

**Owner/budget:** Sol medium, 25 minutes. Split P3a and P3b below into separate writer tasks/reviews.
**Depends on:** P2, R1, R7, H1, C4.
**Files:** create `survival/releases.py`, `scripts/release_manager`,
`services/system/cointos-release-manager.service`, `tests/test_mvp_releases.py`;
modify `scripts/install-survival-plane`, fixed service catalogues and user service `WorkingDirectory`/`ExecStart`.
**Interfaces:** `new_activation(candidate: dict, approval: dict, active_digest: str) -> dict`;
`reduce_activation(state: dict, event: dict) -> tuple[dict, list[dict]]`;
`advance_activation(store: Path, adapters: dict, clock: dict) -> dict`.
Phases: `accepted`, `draining`, `staging`, `switching`, `verifying`, `committed`,
`rolling_back`, `rolled_back`, `blocked`. Effects contain only fixed operation enums and
manifest-owned IDs; no shell text. The old release stays available until postchecks pass.

- [ ] P3a: write a pure rollback transition test:

```python
from survival.releases import reduce_activation

def test_failed_probe_requires_old_release_restore():
    state = {"activation_id": "a1", "phase": "verifying",
             "previous_digest": "a" * 64, "candidate_digest": "b" * 64}
    state, effects = reduce_activation(state, {"kind": "probe_failed", "check_id": "front_canary"})
    assert state["phase"] == "rolling_back"
    assert effects[0]["kind"] == "restore_previous"
    assert effects[0]["digest"] == "a" * 64
```

- [ ] Run `python3 -m unittest discover -s tests -p 'test_mvp_releases.py' -v` and establish failure.
- [ ] P3a: implement durable intent before each external effect, observed postcondition before
  phase completion and replay after process death. Block if approval/base/digest changed.
  Under the R1 fence wait for every local worker; queued work remains durable. A failed probe
  restores the previous release and reruns its checks before reopening ordinary admission.

```python
if event["kind"] == "probe_failed":
    return {**state, "phase": "rolling_back"}, [
        {"kind": "restore_previous", "digest": state["previous_digest"]}]
```

- [ ] P3b: implement installed adapters for immutable user-plane release directories and atomic
  current-link switch. Release files are copied/validated by fixed installer code. Tests,
  builds and candidate scripts execute unprivileged before sealing, never in the root manager.
  User units import the active immutable release, not mutable `/home/david/agent-ecosystem`.
  Absolute runtime/config paths travel explicitly; do not leave `cli.ROOT` ambiguously serving
  as source, workspace and durable-state root. Extract a small path record at process startup.
- [ ] P3b: protect the release manager independently of the guardian/gateway update set. Update
  guardian while old gateway continues; gateway replacement uses one-poller durable-offset
  handoff and bounded response deadline. Never stop both contact and its rollback owner. If
  gateway continuity cannot be demonstrated, leave a protected update blocked with explanation.
  The manager's own upgrade is an operator action outside automatic MVP activation.
- [ ] Test source/runtime-root separation, one-poller switch, changed base, deadline, failed
  startup, failure during rollback and manager restart at switch. Restore failures leave a
  durable blocker and admission closed while the independent contact path reports.
**Acceptance/stop:** a failed user-plane candidate returns to the observed prior release. Protected
targets are admitted only after their separate continuity rehearsal succeeds, never by inference.

## P4 — Live approval, activation and rollback proof

**Owner/budget:** coordinator, 15 minutes plus time waiting for David's actual approval.
**Depends on:** P3, C5, R7, H1. Does not depend on A4/A5; use a test-owned candidate.
**Files:** extend C5's `scripts/mvp_smoke`, `tests/integration/test_mvp_flow.py`;
update `docs/operations.md`, `agent_notes/mvp_acceptance.md` with sanitized evidence.
**Interfaces:** smoke scenario names `approval`, `rollback`, `protected_release_rehearsal`;
outputs contain approval/candidate/activation IDs, old/new release digests and observed checks.

- [ ] Offline, send an authenticated approval through the actual gateway parser to the release
  reducer and fake installed adapters. Prove unapproved/changed candidates cannot switch.
- [ ] Run `python3 -m unittest discover -s tests/integration -p 'test_mvp_flow.py' -v`.
- [ ] Drain workers and observe completion before entering smoke. Prepare a harmless real
  candidate in an isolated workspace, independently verify it, and let Coin request approval.
  While approval is pending, contact and unrelated safe work may continue after releasing the
  fence; acquire and drain again only after approval arrives. Silence is not approval.
- [ ] After actual approval, observe old/new digest and user-process identity, front reply and
  bounded health checks. Then exercise a separately approved test candidate with a deliberately
  failing isolated canary; require restoration and post-rollback contact before releasing work.
- [ ] Rehearse protected activation with the unchanged approved release and fixed rollback
  owner. Mark protected self-update operational only if actual contact continuity and recovery
  checks pass. Otherwise record the exact blocked target; do not claim full protected updating.
- [ ] Confirm no extra poller, model request, orphan worker or OOM increment. Record results
  without approval-message bodies or credentials. Commit only the evidence/documentation.
**Acceptance/stop:** Coin approval governs real activation; failed candidate restores the live
system; no missing approval or failed protected rehearsal is relabeled success.
