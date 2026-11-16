---
status: green
revised_at: "2026-11-16T11:21:21+11:00"
---

Cointel is three separate bot identities on one CointOS daemon, ledger, scheduler, gateway and shared local model runner. The three-installation experiment has been rolled back; do not deploy separate daemons for these identities.

- Cointel Professional is stationed in `~/Work` and serves employee work under professional disclosure policy.
- Cointel Amateur is stationed in `~` and serves general workstation tasks.
- Cointel Personal is stationed in `~/Personal`; its content must never reach a hosted model. Retain Personal's content only as needed to construct its context and carry out retained user instructions; additional diagnostic logs and readily accessible OpenCode session copies are unwanted. Personal sets retain_archive=false and retain_diagnostics=false: its archive is physically pruned to the configured rolling window, turn journals/request captures and persistent inference checkpoints are disabled, and dashboard reply previews are suppressed. Existing turn logs, 57 captured requests and obsolete context caches were removed without displaying contents. Necessary retained instructions, deliberately saved files/knowledge and the locally readable rolling context remain. Delegated Operators still retain normal task/session storage; these controls cover Coin itself.

Knowledge flow is asymmetric by user direction: Personal may use work knowledge; Professional must not use personal knowledge. Current broad filesystem/Bash access does not technically enforce this boundary. Hosted-model disclosure restrictions still apply.

Each identity requires independent bot credentials, name, identity slug, conversation archive, intake, notifications, receipts and conversation owner. Shared scheduling must never mix their inference state or history. Telegram is one transport: other sources must reach the same identity through durable intake rather than a separate turn implementation.

`config/coins/*.json` and `cointos/coins.py` define profiles. `COINTEL` selects the profile, `state/coin-<identity>` separates archives, and the gateway conversation owner is `<identity>/<user digest>`. `how/do/the/cointel/identities/run.md` owns deployment and assisted qualification. Knowledge access remains governed by root policy; identity selection grants no additional access.

One daemon and all three identity services are active after the resident-lifetime repair. The user accepts correctly stationed bots with separate identities and conversations; hard filesystem confinement is not required or planned. Durable generic intake remains unfinished. Personal data must remain outside hosted debugging context.
