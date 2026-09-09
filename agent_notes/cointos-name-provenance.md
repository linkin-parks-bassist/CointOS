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

The operating-system claim is intentional, not apologetic. David chose **CointOS**
partly in answer to the contemporary fashion for calling agentic Python systems
"operating systems" when they categorically do not perform an operating system's
work. CointOS may sit several semantic layers above a conventional machine kernel,
but it is intended to earn the name by supplying the corresponding agent-level
mechanisms rather than by borrowing the metaphor for branding.

David clarified this meaning to Codex agent `/root` on 2026-09-09. Agents are the
processes. A CPU-side kernel schedules their execution on the GPU preemptively,
according to priorities and accounted service. It preserves each agent's complete
logical and inference state across suspension and resumption. GPU memory, RAM and
disk form managed residency tiers; disk backs agents which are alive but not in the
working set. Tools, terminals, messaging and networks are scheduled I/O. Leases and
capabilities govern ownership and authority. Failure, recovery and durable identity
belong to the system rather than to an accidental model-server process.

The resulting parallelism is the operating-system kind: many independently
persistent agents make interleaved progress over scarce physical execution
capacity. More agents may reduce each agent's service rate or increase its waiting
time, but must not silently divide its context capacity. Compatible work may execute
concurrently or in batches when useful; that remains an implementation optimization
beneath the scheduling contract. An agent waiting for I/O need not occupy the GPU,
and an inactive agent need occupy no inference slot at all.

Linux owns processes, pages and devices at their literal machine level. CointOS
owns agents, inference state, authority, knowledge and tool work at a higher level
of meaning. The machine obligations recur: preemption, scheduling, memory and I/O
management, accounting, isolation, suspension, restoration and progress. The year
is 2026; the processes have changed.

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
