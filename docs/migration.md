# Migration and bootstrap

## Reproducible repository state

This milestone needs Ubuntu, Python 3.10 or newer, Bash, Git, and systemd user
units only. It has no Python package dependencies. Clone the repository into
`~/agent-ecosystem`, run `./scripts/ecosystem init`, then run the tests.

Runtime state is intentionally untracked. Back up `state/`, `logs/`, `projects/`,
and both inbox directories separately, subject to project data-handling policy.
Restore those directories before restarting triggers. Preserve permissions and
verify job input hashes before processing.

Lemonade model weights are not required by milestone 1. Future model integration
must record reproducible model/checkpoint manifests rather than commit weights.
Telegram secrets and proprietary artifacts must never enter this repository.

## Validation

```bash
python3 -m unittest discover -s tests -v
./scripts/ecosystem status
```

Systemd units are opt-in; follow `docs/operations.md` only after approval.

