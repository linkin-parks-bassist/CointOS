# How CointOS got its name

Recorded by Codex agent `/root` from David's account on 2026-09-04.

The name accumulated backwards through several jokes rather than being designed
top-down.

David has a habit of finding humour in darker pieces of United States history; his
Discord name `MKUltraScale` is one example. That made **Cointelpro** a natural joke
for the Telegram bot. Because David also uses the system for work, it became
**Cointelprofessional**.

Another layer was hiding inside the word: David works with AMD, and AMD and Intel
are a kind of industry dual, so **coin-tel** fits an AMD professional who is, quite
literally, a “cointel professional.”

The long name then underwent repeated identity-preserving corruption:

```text
Cointelprofessional -> Cointelpro -> Coin -> CoinToss
```

`CoinToss` sounded like `CentOS`. At that point the surrounding project acquired
its proper name: **CointOS**.

The operating-system analogy is intentional, not apologetic. CointOS has scheduling,
resource admission, process supervision, durable jobs and state transitions,
messaging/IPC-like boundaries, recovery, service lifecycle, and an operator control
surface. It is not a kernel, but David does embedded and hardware-near engineering;
the name reflects the system's actual architectural role rather than generic web-app
branding.

Canonical usage going forward:

- **CointOS**: the whole local agent operating environment/project.
- **Cointelprofessional**: the permanent Telegram control-plane identity.
- **Cointelpro**, **Coin**, and **CoinToss**: progressively shortened/corrupted names
  for that same identity; they do not denote separate agents.

The physical repository directory was still `/home/david/agent-ecosystem` when this
note was written because live services resolved that path. Rename it only through a
verified lifecycle operation after the permanent model-independent gateway is live;
do not take Cointelprofessional offline merely to make the filesystem spelling catch
up with the canonical name.
