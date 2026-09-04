### Task 5 Report: Root-owned units and offline process integration

**Date:** 2026-09-04

**Agent:** Codex agent `/root/plan2_task5_complete`

**Provenance:** David's personal repository; no external publication or deployment

**Deliverable:** An installable, permanent Cointelprofessional survival-plane package with offline evidence for its process, permission, socket-activation, and systemd contracts.

## Result

Task 5 is complete in the repository. Nothing was installed, enabled, started,
reloaded, or written to live system paths. The installer defaults to install-only;
activation remains reserved for Plan 5's credential-aware live acceptance sequence.

The package now contains:

- a dedicated survival slice;
- a `Type=notify` Telegram gateway under the dedicated
  `cointelprofessional` account;
- a root guardian with `Accept=no` socket activation;
- main-process-owned readiness and watchdog notification;
- an idempotent installer which creates and validates identities, realizes a
  root-owned immutable code snapshot, applies exact directory/file modes, verifies
  the installed units, and performs no `systemctl` operation by default;
- group-safe atomic records for only the shared Telegram inbox and critical outbox;
- 17 static/disposable-process integration tests, including real Unix credentials,
  real fork/restart behavior, real notification datagrams, and a staged installer
  executed twice without root.

## Audit of the inherited draft

The interrupted implementation's 16 tests passed, but emitted unclosed-pipe
`ResourceWarning`s and did not establish the production contract. A replacement
behavioral test run produced `Ran 16 tests` with 7 failures and 4 errors before the
production repairs. The reproduced defects included:

- units executing `%h/agent-ecosystem` as the dedicated user rather than an
  installed snapshot;
- a literal `NOTIFY_SOCKET`, speculative external Documentation URLs, inconsistent
  state/socket paths, fixed Unix identities, and a root-only command socket;
- child workers emitting watchdog datagrams even though `NotifyAccess=main` permits
  only the service main process;
- a guardian that unlinked and rebound systemd's inherited socket;
- an installer that neither created identities nor corrected existing directory
  ownership/modes, placed incomplete entry points outside their imports, swallowed
  verification/activation failures, and mutated systemd even on its nominal
  install-only route;
- tests which accepted those placeholders and did not observe process ownership,
  real loop wedges, socket activation, idempotence, or cleanup.

The first shared-spool audit then exposed a second load-bearing flaw: setgid
directories alone were insufficient because temporary records were published as
`0600`. Focused TDD produced `Ran 47 tests` with 3 failures and 1 error before that
repair. The failures showed shared inbox/critical-outbox records at `0600`, an
ordinary append at the caller's umask-derived mode, and no explicit shared-record
policy.

A final staged self-review found that `/run` is ephemeral and the socket unit would
otherwise recreate its parent as `root:root` after reboot. A focused static test
failed before the unit repair. The guardian service now owns the runtime-directory
contract described below.

## Implementation

### Service ownership and supervision

- `cointelprofessional-gateway.service` uses `Type=notify`,
  `NotifyAccess=main`, `User=cointelprofessional`, unlimited start attempts,
  250 ms restart delay, a 10 s watchdog, and the survival slice. It receives the
  private command and shared-spool groups as supplementary memberships.
- `LoadCredential=telegram_bot_token:/etc/cointelprofessional/telegram_bot_token`
  is the only token path. systemd supplies `CREDENTIALS_DIRECTORY` and
  `NOTIFY_SOCKET`; neither is hard-coded.
- Both Python services execute modules only from
  `/usr/local/lib/cointelprofessional-survival`, never from a home directory or
  mutable checkout.
- Gateway workers retain their Task 3 durable heartbeat ownership and signal only
  their parent after healthy loop completion. The main PID revalidates both durable
  heartbeats and alone emits `READY=1`/`WATCHDOG=1`. A wedged poller eventually
  becomes stale and stops watchdog renewal; a wedged egress loop stops it directly.
- The guardian main loop emits readiness only after acquiring its listener, renews
  its watchdog on idle accepts and completed lifecycle advances, and does not renew
  while a request is wedged.
- The root guardian uses `cointelprofessional_command` as its primary group and
  systemd `RuntimeDirectory=` policy to restore
  `/run/cointelprofessional` as `root:cointelprofessional_command 0750` after each
  boot. `RuntimeDirectoryPreserve=yes` prevents guardian restarts from deleting the
  socket unit's independently owned node.
- The guardian consumes exactly one systemd fd 3 when `LISTEN_PID`/`LISTEN_FDS`
  identify the current process. It closes but never unlinks a systemd-owned socket;
  the existing direct-start path continues to own and remove its own node.

### Identities, paths, and installation

The controller-selected identities are deliberately distinct:

```text
cointelprofessional_command  private command-socket group
agent_ecosystem_io           shared durable-spool group
cointelprofessional          unprivileged gateway service account
root                         guardian service account
```

The gateway is a supplementary member of both groups. David is added only to the
shared-spool group. The socket is `root:cointelprofessional_command 0660`; the
socket directory is `root:cointelprofessional_command 0750`; and the shared store
is `root:agent_ecosystem_io 2770`.

`scripts/install-survival-plane` accepts only no argument or literal `--enable`.
An invalid argument is not repeated in diagnostics, so a mistakenly supplied
credential cannot be disclosed. Each run creates or validates the service account,
creates the groups when absent, reapplies all owners and modes, resolves numeric
gateway/David UIDs, creates a root-only `guardian.env`, copies every required module
and entry point into the immutable snapshot, installs all four units, and performs
one fatal `systemd-analyze verify`. The default route makes no `systemctl` call.
The explicit `--enable` route performs `daemon-reload` and one exact `enable --now`
operation without suppressing errors.

The integration backend stages the filesystem under a temporary root and replaces
only account/system commands. Real file copies and mode changes occur in that
temporary tree. The test executes the installer twice, observes dynamic non-root
UIDs, exact owner/group requests and final modes, absence of credential
placeholders, one verification per run, no install-only systemd mutation, and the
exact explicit activation sequence.

### Shared and private record publication

Generic record APIs now default explicitly to `0600` and accept only the exact
policies `0600` and `0660`. Boolean, intermediate, and over-permissive modes are
rejected before a directory is created.

Atomic replacement and exclusive publication set and fsync the requested mode on
the still-inaccessible temporary inode before `os.replace`/`os.link`. A permission
failure leaves neither a final record nor a temporary artifact. Append records are
opened with and explicitly narrowed to the private mode before any event is
written. This preserves the previous durable-before-publication, directory-fsync,
exclusive-create, replay, and crash invariants without a chmod-after-publication
window.

Only the semantic Telegram fingertips for inbox and critical-outbox initial writes
and state replacements request `0660`. Commands, gateway submissions,
acknowledgements, worker/aggregate heartbeats, quarantine, lifecycle state, result,
and event records retain the private default. The installer-created setgid store
supplies inherited `agent_ecosystem_io` group ownership.

## Architectural audit

The result follows the repository manifesto's relevant laws:

- **Fractional distillation:** process policy is represented once in systemd units;
  identity realization once in the installer; record visibility once as the two
  validated record modes; and lifecycle health once in the existing durable worker
  heartbeats. No parallel supervisor or lifecycle model was introduced.
- **Vertical layerwise agnosticism:** gateway and guardian loops know only the
  minimal notification function and their existing health/state contracts. The
  notifier knows only Unix datagrams. Units and installation own Linux/systemd
  realization without leaking those details into lifecycle semantics.
- **Contract-led modularity:** explicit boundaries are systemd's inherited socket
  fd, `NOTIFY_SOCKET`, `SCM_CREDENTIALS`/`SO_PEERCRED`, installed environment paths,
  and the `0600`/`0660` publication policy. Tests cross those same boundaries rather
  than mocking the behavior under review.
- **Semi-permeable horizontal boundaries:** only the gateway crosses into the
  command group; only the two shared spool record families cross from private to
  group-visible state; and the guardian remains the sole root mutation fingertip.
- **Machine reality:** ownership, numeric UIDs, fd 3, Unix socket modes, setgid
  inheritance, pre-publication inode modes, fsync ordering, forked PIDs, watchdog
  timing, and failure propagation remain explicit. The implementation uses
  functions and plain data only; it introduces no classes or hidden mutable object
  state.

## Verification evidence

All final verification was run from `/home/david/agent-ecosystem` without root,
network, credentials, live installation, or a systemd manager mutation.

```sh
python3 -m unittest tests.integration.test_survival_processes -v
```

Observed: `Ran 17 tests in 5.919s`, `OK`, with no warning or traceback.

```sh
python3 -m unittest \
  tests.test_survival_records tests.test_survival_protocol \
  tests.test_survival_lifecycle tests.test_survival_gateway \
  tests.test_survival_guardian tests.test_system_control \
  tests.integration.test_survival_processes -v
```

Observed: `Ran 117 tests in 7.672s`, `OK`, with no warning or traceback.

```sh
python3 -m unittest discover -s tests -v
```

Observed: `Ran 225 tests in 3.500s`, `OK`, with no warning or traceback. The
repository discovery configuration does not descend into the un-packaged
`tests/integration` directory, so the explicit 117-test command above is the
load-bearing integration run.

```sh
systemd-analyze verify \
  services/system/cointelprofessional-survival.slice \
  services/system/cointelprofessional-gateway.service \
  services/system/cointelprofessional-guardian.socket \
  services/system/cointelprofessional-guardian.service
```

Observed: exit 0 with empty stdout/stderr.

```sh
bash -n scripts/install-survival-plane \
  scripts/cointelprofessional-gateway scripts/cointelprofessional-guardian
python3 -m py_compile survival/systemd_notify.py survival/gateway.py \
  survival/guardian.py survival/records.py survival/telegram_api.py \
  tests/integration/test_survival_processes.py \
  tests/test_survival_records.py tests/test_survival_gateway.py
git diff --check
```

Observed: every command exited 0 with no output. `shellcheck` is not installed in
this environment, so no shellcheck result is claimed.

```sh
pgrep -af \
  '[g]ateway-restart.py|[g]ateway-notify.py|[g]uardian-notify.py|[g]uardian-activation.py'
```

Observed: exit 1 with no output, proving the disposable process tests left none of
their harnesses running.

## Constraints retained for Plan 5

- No live install, credential read/write, service activation, daemon reload, or
  systemd mutation was performed.
- The `--enable` route has exact offline evidence but intentionally has not been
  exercised against the live manager.
- Real credential presence, actual account allocation, live root ownership, reboot
  persistence, restart storms, watchdog termination, Telegram reachability, and the
  end-to-end `STATUS`/`RESTART`/`RESET` acceptance sequence remain Plan 5 work.
- `WatchdogSec=10s` is intentionally shorter than the 60 s durable poll-heartbeat
  lease. A hard poll wedge stops renewal once that existing Task 3 lease expires;
  ordinary 25 s Telegram long polls remain healthy because the egress worker asks
  the main process to revalidate both durable heartbeats every two seconds.

## Files in this commit

- `services/system/cointelprofessional-survival.slice`
- `services/system/cointelprofessional-gateway.service`
- `services/system/cointelprofessional-guardian.socket`
- `services/system/cointelprofessional-guardian.service`
- `survival/systemd_notify.py`
- `survival/gateway.py`
- `survival/guardian.py`
- `survival/records.py`
- `survival/telegram_api.py`
- `scripts/install-survival-plane`
- `tests/integration/test_survival_processes.py`
- `tests/test_survival_records.py`
- `tests/test_survival_gateway.py`
- `docs/operations.md`
- `.superpowers/sdd/2026-09-04-cointelprofessional-02-survival-plane-lifecycle/task-5-report.md`

## Fix round 1/5 — atomic installer deployment boundary

**Agent:** Codex agent `/root/plan2_task5_complete`

### Review finding and root cause

Task 5 review reported 0 Critical, 1 Important, and 0 Minor findings. The Important
finding was reproducible: the installer copied code, configuration, documentation,
and four units directly over their authoritative paths, then verified the already
published unit files. Any construction or verification failure could therefore
leave a service restart observing an internally mixed release.

This was not a missing rollback around one copy operation. The root cause was the
absence of a single representation and commit point for an installed release.

### RED evidence

The failure tests use a private copied source tree so a second release can differ
from the first without modifying the checkout. They run the real installer and real
filesystem operations below a temporary install root, replacing only account,
systemd, and injected-failure command boundaries.

Before changing the installer, construction and verification were failed after a
different gateway and guardian unit had begun deployment, and commit failure was
injected. The run observed `Ran 20 tests in 9.215s` with exactly 3 failures: both
pre-commit failures changed the byte-for-byte installed-tree digest, while the old
installer had no atomic commit operation to fail.

A verifier-boundary test then required the candidate root's final mode and all code,
entry-point, documentation, configuration, and unit families to exist before unit
verification. It observed `Ran 20 tests in 7.336s` with 6 expected failures because
the candidate still had its private construction mode at verification time.

Finally, an injected interruption immediately after the current-link rename
observed `Ran 21 tests in 11.601s` with 1 failure: cleanup removed the now-current
release during the narrow interval before the shell cleared its candidate marker.

An integrity mutation then changed only the published release root's mode. The
22-test run failed exactly that test because the initial content identity covered
descendants but not the root itself. The final identity includes both.

### Resolution

- `/usr/local/lib/cointelprofessional-survival` is now a stable release container.
  Candidates are built beneath its `releases/` directory, on the same filesystem as
  the commit point, and remain mode `0700` while incomplete.
- Every Python module, entry point, operations document, timing configuration,
  generated numeric-UID environment, and systemd unit is copied into the candidate
  with its final owner and mode. The candidate root changes to its final `0755`
  mode only after construction is complete.
- `systemd-analyze verify` receives only the candidate's four unit paths and must
  succeed before any release directory is published.
- A release identity hashes the release root and every relative path, entry kind,
  mode, numeric owner, numeric group, and regular-file byte digest. An
  already-present content-addressed release must reproduce that identity exactly or
  installation fails explicitly.
- Stable code, entry-point, documentation, configuration, and `/etc/systemd/system`
  unit links all resolve through one `current` link. Unit updates therefore cannot
  publish four independently versioned files.
- A complete candidate is renamed into `releases/` atomically. A temporary symlink
  is then renamed over `current` with `mv -T`; this single same-filesystem rename is
  the authoritative commit operation.
- Construction, verification, or pre-rename commit failure removes only temporary
  or newly published uncommitted content. The prior current link and its full
  release remain byte-for-byte unchanged. Cleanup re-reads `current` before removing
  a candidate, so an interruption immediately after a successful rename cannot
  delete the newly authoritative release.
- Successful commits retain the prior complete content-addressed release. Repeating
  an identical install reuses the same verified identity and leaves the installed
  tree and current target unchanged.

This is the manifesto's transactional-construction boundary expressed directly in
filesystem terms: an inaccessible candidate, a verified complete value, and one
atomic symbolic publication. There is no compensating sequence which attempts to
reconstruct overwritten state.

### GREEN evidence

```sh
python3 -m unittest tests.integration.test_survival_processes -v
```

Observed: `Ran 22 tests in 13.152s`, `OK`, with no warning, traceback, leaked
process, live-system write, credential access, or network access.

```sh
python3 -m unittest \
  tests.test_survival_records tests.test_survival_protocol \
  tests.test_survival_lifecycle tests.test_survival_gateway \
  tests.test_survival_guardian tests.test_system_control \
  tests.integration.test_survival_processes -v
```

Observed: `Ran 122 tests in 14.956s`, `OK`.

```sh
python3 -m unittest discover -s tests -v
```

Observed: `Ran 225 tests in 3.741s`, `OK`, with no warning or traceback. As before,
repository discovery does not descend into the un-packaged integration directory;
the explicit commands above cover it.

### Remaining boundary

No installation or activation was performed. Old complete content-addressed
releases are intentionally retained rather than pruned during Task 5; any future
retention policy is a separate destructive-operation decision. Live ownership,
manager reload, activation, restart, reboot, watchdog, credentials, and Telegram
acceptance remain Plan 5 work.

### Post-commit manifesto audit and first-install rollback closure

The updated workspace doctrine was read in full after the first atomic-installer
commit. Auditing the implementation against reachable partial construction found
one narrower instance of the same transactional cause: on a first installation,
the stable code, configuration, and unit symlinks were created before the
`current` rename. They could not resolve without `current`, so no release became
authoritative, but an injected commit failure left those broken wrappers visible.

A focused RED run observed `Ran 23 tests in 14.048s` with exactly one failure:
`test_installer_initial_commit_failure_leaves_no_published_wrappers`. The installer
now records only wrappers it creates during the current invocation. Cleanup reads
the authoritative `current` target: before commit, it removes those wrappers in
reverse order together with the uncommitted release; after a successful atomic
rename, including an injected interruption before the next shell statement, it
retains both the complete release and its wrappers. Existing wrappers are never
registered for rollback and therefore remain untouched during a failed update.

The architectural review questions resolve as follows:

1. Source files become a private candidate with explicit installed metadata, then
   a verified content-addressed release, then an authoritative value through
   `current`. Bytes often pass unchanged, while ownership, mode, provenance, and
   publication role change at the installation boundary.
2. The candidate contract is root-owned, same-filesystem, complete before verify,
   and non-authoritative before the `current` rename. Pre-commit failure preserves
   the prior release or restores the empty first-install surface; post-rename
   failure exposes only the complete new release and retains the old one.
3. Release names, staging names, hashing, rollback bookkeeping, and rename mechanics
   remain installer concerns. Service code and systemd units consume only stable
   installed paths.
4. Literal paths, modes, owner/group spellings, unit filenames, digest framing, and
   filesystem commands occur at the installer fingertip. They are not reconstructed
   by gateway, guardian, lifecycle, or record code.
5. Code, entry points, configuration, documentation, and units legitimately cross
   horizontal regions together because they form one release. Plain arrays and
   direct functions construct, verify, identify, and publish that shared tree.
6. The install transaction contains no control cycle. Existing watchdog and
   lifecycle feedback remains explicit in the service contracts and was not given
   a second route by this fix.
7. The boundaries are semi-permeable: the digest traverses the real candidate and
   tests inspect the real staged filesystem. No mirrored release model, callback
   choreography, or actor-like installer abstraction was introduced.
8. Varying file families have coherent owners in `python_modules`, `entry_points`,
   and `units`; visibility is owned by the single `current` reference. Tests repeat
   only acceptance expectations, not runtime policy.
9. Replacing release storage would affect the installer and its adjacent tests,
   while services retain their stable path contract. Adding a module or unit changes
   its owning list and focused acceptance evidence, not unrelated runtime layers.
10. An active release cannot be incrementally overwritten. Incomplete candidates
    remain unreferenced; failed first-install wrappers are removed; failed updates
    retain the byte-for-byte prior tree; and interruption after commit leaves a
    complete digest-identified tree. Identity and state directories may already
    exist because they are installation prerequisites, not a semantic release.
11. Injected construction, verification, pre-commit, first-install commit, and
    post-commit failures exercise the boundary. Content mutation and root-mode
    mutation exercise release identity. Live manager and power-loss durability
    remain deliberately unintegrated for Plan 5 rather than represented by an
    offline placeholder.
12. The incremental-copy route has been removed. Candidate, release, reference, and
    wrapper roles are distinct, with one semantic cutover rather than compensating
    overwrite/rollback sequences.
13. Root ownership, final modes, complete verification, content identity, and
    same-filesystem atomic rename are laws of this installer. Activation is the
    explicit `--enable` policy; the alternate install root is solely an offline
    test fingertip.
14. A future module extends the module list; a future unit extends the unit list,
    verifier arguments, and wrapper acceptance test. The release transaction and
    service consumers otherwise remain unchanged, demonstrating a prepared joint
    rather than distributed version selection.

Fresh GREEN evidence after this closure:

```sh
python3 -m unittest tests.integration.test_survival_processes
```

Observed: `Ran 23 tests in 14.178s`, `OK`.

```sh
python3 -m unittest \
  tests.test_survival_records tests.test_survival_protocol \
  tests.test_survival_lifecycle tests.test_survival_gateway \
  tests.test_survival_guardian tests.test_system_control \
  tests.integration.test_survival_processes
```

Observed: `Ran 123 tests in 16.308s`, `OK`.

```sh
python3 -m unittest discover -s tests
```

Observed: `Ran 225 tests in 4.134s`, `OK`, with only the suite's existing expected
application stdout and no warning or traceback.

```sh
systemd-analyze verify \
  services/system/cointelprofessional-survival.slice \
  services/system/cointelprofessional-gateway.service \
  services/system/cointelprofessional-guardian.socket \
  services/system/cointelprofessional-guardian.service
```

Observed: exit 0 with empty stdout/stderr.

## Fix round 2/5 — abrupt first-install publication boundary

**Agent:** Codex agent `/root/plan2_task5_complete`

### Re-review findings and root cause

The first scoped re-review returned two binding Important findings. Both arose from
one ordering error: stable snapshot, configuration, and unit wrappers were created
before the atomic `current` rename. The round-1 EXIT trap removed them after an
ordinary command failure, but an abrupt process death cannot run shell cleanup and
therefore left reachable wrappers dangling through a nonexistent `current`.

The corresponding test used a fake `mv` failure which returned normally. It proved
rollback on an ordinary shell exit, not the abrupt interruption boundary claimed
by the report.

### RED evidence

The new test's fake `mv` fingertip sends `SIGKILL` to the installer shell immediately
before the `current` rename. The fake then exits, so the test process regains control
without the installer's EXIT trap having run. It checks the literal stable snapshot,
configuration, and all four unit paths, and independently checks that the abandoned
content-addressed release is nevertheless complete.

Before changing the installer, the focused run observed `Ran 24 tests in 14.459s`
with exactly one failure:
`test_installer_abrupt_pre_commit_interruption_publishes_no_wrappers`. The stable
wrappers remained visible and dangling after the killed installer.

### Resolution and architectural re-audit

- Wrapper targets and paths now have one paired representation. The installer
  preflights every existing path after candidate verification without creating or
  changing anything. A mismatched symlink or blocking non-symlink therefore fails
  while the old release remains authoritative.
- A complete candidate is still identified and placed under `releases/` before the
  commit. The one same-filesystem rename of `current` remains the sole semantic
  cutover.
- Existing update wrappers are untouched before that rename and consequently change
  meaning together only when `current` changes.
- Missing wrappers, including every wrapper on a first installation, are created
  only after `current` names a verified complete release. Publication of individual
  wrapper names can be interrupted, but every name which becomes visible resolves
  to the same complete authoritative release; no dangling or mixed-version route is
  constructible by this ordering.
- An abrupt pre-commit interruption may leave a complete, unreferenced
  content-addressed release and a private `.commit.*` directory. Neither is an
  authoritative fingertip. Prior complete releases remain retained, and a later
  idempotent install validates/reuses the release.

This keeps vertical details localized: gateway, guardian, units, and record logic
still know only stable installed paths. Literal symlink targets, path conflict
checks, and rename ordering remain in the installer fingertip. Horizontally, code,
configuration, documentation, and units are deliberately traversed together as one
release through plain paired arrays. The boundary is semi-permeable for validation
and hashing but has one authority transition. No cleanup path is treated as a
substitute for transactional construction, and no second semantic version route
was introduced.

### GREEN evidence

```sh
python3 -m unittest tests.integration.test_survival_processes
```

Observed after the final test refactor: `Ran 24 tests in 14.767s`, `OK`. The abrupt
pre-commit case proves no stable wrapper is present while the retained unreferenced
release is complete. The existing post-commit interruption case continues to prove
that `current`, snapshot, and unit paths all expose the complete new release while
the prior release remains retained.

```sh
python3 -m unittest \
  tests.test_survival_records tests.test_survival_protocol \
  tests.test_survival_lifecycle tests.test_survival_gateway \
  tests.test_survival_guardian tests.test_system_control \
  tests.integration.test_survival_processes
```

Observed: `Ran 124 tests in 16.750s`, `OK`.

```sh
python3 -m unittest discover -s tests
```

Observed: `Ran 225 tests in 4.175s`, `OK`, with only the suite's existing expected
application stdout and no warning or traceback.

```sh
systemd-analyze verify \
  services/system/cointelprofessional-survival.slice \
  services/system/cointelprofessional-gateway.service \
  services/system/cointelprofessional-guardian.socket \
  services/system/cointelprofessional-guardian.service
```

Observed: exit 0 with empty stdout/stderr.
