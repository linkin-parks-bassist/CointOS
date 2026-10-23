---
status: green
revised_at: "2026-10-15T23:54:34+11:00"
checked_at: "2026-10-12T12:45:58+11:00"
---

Every task gets a generated personal name (`tasks.create` → `names.invent`), unique among current tasks and retained for its lifetime. Paused/resumed runs keep that name; a new task gets a new one. Agent IDs such as `worker-0b23e3` identify transient runs. Admission reserves each run directory exclusively, skipping live, exiting and issued/persisted key identities. Existing directories, files and symlinks remain unavailable. The ledger lock prevents a new follower launching before registration: thread or key failure leaves task and ownership unchanged. Keys are drawn outside persisted/live/known-ended ownership and persist before adoption. Exact adoption is idempotent; conflicting owners and actor rotations are refused. Key registries require regular, non-symlink JSON. Unreadable, malformed or ambiguous data, including duplicate fields/key values, are refused without rewriting identities. Only a genuinely absent registry initializes Coin's fixed key; an existing registry without that key is refused unchanged. Launch metadata uses exclusive creation. Old IDs remain adoptable; an exact agent/task relation or current receipt identifies surviving ownership. A displaced running task requeues; a live receipted survivor remains watch-only.

Task IDs use `PROJECT:NAME`. Queued work keeps its item ID across assignment revisions. Numbered maintenance and Operator tasks reserve IDs against both existing tasks and queue records. A new queue proposal cannot claim an existing task ID, including retained cancelled history; choose another name. Identical retries of an existing proposal remain idempotent. Recovery controllers have their own IDs and refer to the canonical work/version through `repair_origin`; `cointos task` follows that link to show the current queue record alongside historical task evidence.

Personal names are generated, never selected from a list (the user's requirement): `cointos/names.py` assembles two or three syllables from weighted onset, vowel and coda inventories drawn from many languages. Plain sounds are common, exotic sounds rare; joining syllables avoids consonant piles, and a filter rejects unpronounceable clusters. Results include Gartan, Virta, Xorzak, Rakhi, Zozu and Zedritek; a few clunky names are accepted.

Names appear in `prompts.identity` ("Your name is …"), delivered messages (`<message from="NAME (TASK)">`), `cointos_peers`, `cointos agents` and dashboard cards. Only runs launched after the name exists see it in their own prompt.

Evidence: `tests/test_mcp.py` checks generated names, identity/messages and linked-record inspection. `tests/test_tasks.py` and `tests/test_queues.py` check identity collisions in both creation orders, cancelled history, identical retries and legitimate revisions. `tests/test_run_admission.py` covers run aliases, historical artifacts, persistence/thread failures, corrupt/unreadable key registries and exact restart ownership.

Proof:

```bash
cd "$(git rev-parse --show-toplevel)" && python3 -m unittest -q tests.test_tasks tests.test_queues tests.test_mcp tests.test_run_admission tests.test_authority_storage
```
