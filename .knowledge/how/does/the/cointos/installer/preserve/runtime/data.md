---
status: "unverified"
created_at: "2026-09-14T22:57:33+10:00"
scope: "local"
source: "scripts/install-cointos same_reconciled_knowledge; actual metadata-only conflict; tests/test_install_cointos.py expanded regression"
updated_at: "2026-09-14T23:54:02+10:00"
---

The installation payload is explicit: ecosystem, survival, scripts, config, roles, services, infrastructure and steward-tasks, plus the project `.knowledge`, AGENTS.md and README.md. Install directly into the selected runtime prefix so current source-relative ROOT resolves to the installed root. Never copy or replace state, logs, development, projects, inbox, models, secrets, Git metadata or standalone global knowledge.

Stage payload before replacing install-owned paths, preserve modes, serialize installations with a lock and retain the prior payload as rollback material. Existing edited configuration is retained; new defaults can be supplied beside it for review. Record source revision/local modifications and shipped configuration hashes to distinguish later local edits. Directory replacement is transactional against handled errors, not an atomic whole-application upgrade under crashes or concurrent live execution. Do upgrades at a drained service boundary; the installer does not start/restart services or change system configuration.

Implemented in `scripts/install-cointos`: runtime executable paths in deployed prompts/configuration/unit templates target the prefix. Development workspace registry and canonical KT pointers still reference their independent source/knowledge owners. An isolated install plus installed CLI/import checks and repeat upgrade tests are required before real installation.

Six focused tests exercise independent installed commands, upgrades preserving operational records/config/knowledge, replacement rollback, dry run/missing assets/symlink rejection and divergent knowledge conflict. Prior install-owned code is retained at `.cointos-previous`; configuration overrides retain `.dist` defaults. No live service is switched by installation.

Operational copy completed 2026-09-14 into `/home/david/.CointOS`; installed `scripts/ecosystem --help` succeeds from the checkout. The application/project knowledge payload was copied and standalone KT registered `/home/david/.CointOS/.knowledge` as `cointos`. Root-wide lookup is now allowed: David explicitly requested execution of the approval call; the public KT prompt was confirmed and a `cointos:` lookup from `/tmp` succeeded. No services or backend configuration were changed.

Approval completion: David explicitly requested that the agent execute the access call. `kt access /home/david/.CointOS/.knowledge allow --scope all` saved allow; outside-project `kt open cointos:what/is/the/intended/cointos/installation/layout.md` succeeded. The installer now automatically saves the authorized all-directory grant, including noninteractive agent runs. No registry internals were edited.

Blanket installation policy: David explicitly authorized automatic all-project access to installed CointOS knowledge, without an interactive installer prerequisite. Six installer tests pass, including real CLI noninteractive repeat installation/approval in an isolated registry and outside-directory `cointos:` lookup; an unrelated registered root remains ask and general bypass remains disabled. The implementation uses KT’s public register/access CLI through a bounded approval terminal, without registry-internal writes.

On upgrade, divergent source/runtime knowledge is a deliberate safety stop: the installer compares current installed content and newly rendered source against the previous shipped hash. If both differ, installation aborts before payload replacement. The 2026-09-14 reactivation attempt stopped at what/is/next.md; its installed relocation amendments were reviewed and the current source projection includes their still-valid constraints. Reconcile each divergent owner revision-safely before retrying; do not bypass the guard or rewrite shipped hashes.

Revision-safe kt amend updates source/updated_at metadata, so reconciled identical answers previously still failed the byte-hash guard. same_reconciled_knowledge now tolerates only differing single-line source and updated_at frontmatter fields when every remaining byte is equal, preserving the runtime leaf including its provenance. Body, scope, status, proof and other metadata differences still conflict. The expanded installer regression checks actual reconciled upgrade and continued status-divergence rejection.
