---
status: green
revised_at: "2026-10-24T02:31:27+11:00"
---

Run python3 -m unittest discover from the source repository. Focused checks use dotted module names. Import tests before any cointos module: tests/__init__.py allocates disposable ledger, journal, keys, run paths, snapshot stores, generated knowledge, root registration and kt rewrite state before production imports capture them. Late initialization refuses rather than pretending an environment change can redirect imported state.

To replay fixtures against installed code, put the installed package first on PYTHONPATH and use explicit modules; discovery can prepend the source root:

```bash
PYTHONPATH="$HOME/.CointOS:$PWD" python3 -P -m unittest tests.test_packet_corrections tests.test_isolation
```

A custom runner imports tests first, then checks cointos.__file__/submodule paths. Never import production merely to print its path before isolation. tests.test_isolation covers child-process refusal, isolated journal/ledger writes and real generated-queue/registry publication. Keep fixture events distinct from native acceptance; journal history is evidence and must not be cleared to disguise pollution.

The broader receipt/recovery/publication replay uses these independent groups. They belong in deliberate validation, not one oversized default-timeout leaf proof:

```bash
python3 -m unittest -q tests.test_agent_completion tests.test_authority_storage tests.test_run_admission
python3 -m unittest -q tests.test_operator_recovery tests.test_operator_handback tests.test_operator_boundaries tests.test_blocked_work
python3 -m unittest -q tests.test_replacement_handoff tests.test_recovery.Budgets tests.test_handoffs
python3 -m unittest -q tests.test_cli_terminal tests.test_mcp tests.test_snapshots tests.test_gateway_disconnect tests.test_pre_stop_check
python3 -m unittest -q tests.test_landing.Gate tests.test_landing.Packets tests.test_landing.Incorporation tests.test_landing.Commands tests.test_publication tests.test_restart.PublishedRestart
python3 -m unittest -q tests.test_packet_corrections tests.test_factory_frontier
python3 -m unittest -q tests.test_pipeline_simulator
```

These are commands, not a current test-count or timing guarantee. Check each result independently. Long integration replays can exceed kt's per-proof or MCP renewal budget even when individual tests pass. The completion-model leaf keeps a focused ownership/receipt proof; focused implementation owners retain the other contracts.

Cache fixtures isolate TRANSFERS, restore pins, active cleanup ownership and save reservations. Logical retirement is distinct from physical cleanup; virtual-GB fixtures mock measured headroom while blocked-I/O tests use actual files/TCP. Source qualification evidence is retained in workflow-observation-20261019/snapshot-cleanup-suite.log; historical counts do not describe today's complete suite.

Tests establish mechanisms, not sustained model judgment or product acceptance. Installed validation also uses cointos check and the authorised live scenario. The live-acceptance owner holds native observations; backend experiments and fault simulation have focused procedures. Native-only probes are opt-in and use uniquely named disposable units.
