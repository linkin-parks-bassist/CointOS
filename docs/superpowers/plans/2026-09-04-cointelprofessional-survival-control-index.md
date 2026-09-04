# Cointelprofessional Survival Control Plan Suite

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement permanent Cointelprofessional contact, full `RESTART` and `RESET`, priority fast control, hard subsystem health leases, reported repair/escalation, and evolving subsystem monitors.

**Architecture:** Five ordered implementation plans deliver independently reviewable software. The first stabilizes the currently running user-level system; the second builds the permanent survival plane; the third moves ordinary messages onto mechanically reserved fast control; the fourth adds health and incident recovery; the fifth adds deeper monitors and performs live deployment acceptance.

**Tech Stack:** Python 3 standard library, JSON/JSONL, INI configuration through `configparser`, filesystem queues, Unix sockets, systemd system/user units, Lemonade's loopback HTTP API, and `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-04-cointelprofessional-survival-control-design.md`

## Global Constraints

- Personal orchestration infrastructure; never copy professional or customer material into tests, prompts, Git, or external services.
- Object-oriented programming is forbidden; use functions, plain data, explicit state transitions, and narrow modules.
- Identifiers under our control use lowercase snake_case; constants use uppercase `SNAKE_CASE`.
- Preserve append-only runtime JSONL and all existing user work; do not reset or discard the dirty worktree.
- Roles are nullable advisory context and never an admission gate.
- The gateway and guardian remain outside every destructible lifecycle set.
- Model-generated code never runs as root; root accepts only typed, allowlisted lifecycle requests.
- All touched operational durations come from `config/time.cfg`; monotonic time makes decisions and UTC records events.
- Every task begins with a failing test, ends with focused and regression tests, and receives an independent review before the next task.
- Do not push, enable services, or alter credentials until the live-deployment task explicitly reaches that approved boundary.

---

## Ordered plans

1. [Foundation stabilization](2026-09-04-cointelprofessional-01-foundation-stabilization.md)
2. [Permanent survival plane and lifecycle](2026-09-04-cointelprofessional-02-survival-plane-lifecycle.md)
3. [Priority fast control](2026-09-04-cointelprofessional-03-priority-fast-control.md)
4. [Subsystem health and reported escalation](2026-09-04-cointelprofessional-04-subsystem-health-escalation.md)
5. [Deep monitors and live acceptance](2026-09-04-cointelprofessional-05-monitors-live-acceptance.md)

Each plan is a checkpoint. Run its complete test set and review its diff before
starting the next. The final plan alone installs/enables root-owned services and
performs real Telegram/Lemonade fault injection.

## Specification coverage

| Specification requirement | Owning plan and task |
| --- | --- |
| Existing restart storm, partial emergency, and passing-test gap | Plan 1, Tasks 3–5 |
| Central `time.cfg` and validated live reload | Plan 1, Task 1; Plan 5, Task 1 |
| Optional/unknown roles | Plan 1, Task 2 |
| Permanent gateway, guardian, credential and peer boundary | Plan 2, Tasks 1–5 |
| Durable `RESTART` and `RESET` semantics | Plan 2, Tasks 2 and 4; Plan 5, Task 4 |
| Maximum-priority small-model capacity | Plan 3, Tasks 1–2 |
| Immediate respond-or-dispatch decision | Plan 3, Tasks 3–4 |
| Central subsystem catalogue and active-agent status | Plan 4, Task 1 |
| Per-subsystem health contracts and leases | Plan 4, Tasks 2–3 |
| Direct repair progress and manual escalation | Plan 4, Task 4 |
| Automatic context/death/timeout escalation | Plan 4, Task 4 |
| Largest safely plausible emergency context | Plan 4, Task 4 |
| Staggered five-minute monitor per implemented subsystem | Plan 5, Task 1 |
| Monitor-discovered health gaps becoming required checks | Plan 5, Task 2 |
| Fast Cointelprofessional subsystem questions | Plan 5, Task 3 |
| Full process, Lemonade, Telegram, OOM, and deployment proof | Plan 5, Tasks 4–6 |

Test modules use the repository's function collector; `unittest.TestCase()` is used
only as a standard-library assertion/cleanup context, never as application design.
Temporary roots are created with `tempfile.TemporaryDirectory`, and module roots are
patched with `unittest.mock.patch.object`; no test depends on pytest fixtures.
