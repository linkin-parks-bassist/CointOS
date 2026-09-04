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
