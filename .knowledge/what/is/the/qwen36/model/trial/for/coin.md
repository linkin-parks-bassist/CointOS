---
status: green
revised_at: "2026-10-19T06:11:03+11:00"
---

Qwen3.6-35B-A3B-MTP-GGUF is unloaded and no longer selected for Coin: the earlier choice was MiniCPM, since replaced by the user's shared-Qwen3.8 selection. Short synthetic checks showed useful speed but did not predict real knowledge-tool responsiveness.

The downloaded checkpoint is unsloth/Qwen3.6-35B-A3B-MTP-GGUF:Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf, revision 5bc3e238d916f48a861bac2f8a1990a0e9b7e98d. The [official model card](https://huggingface.co/Qwen/Qwen3.6-35B-A3B) describes 35B total/3B active parameters. The catalogue's 22.1 GB is not an independently hashed local size. Its trial used a 65,536-token MTP lane, batch 512/ubatch 128, poll 0, priority -1, cache-ram 0 and unchanged Coin reasoning caps; the 34 GB admission estimate was not occupied-context measurement.

Native short fixtures selected correct NZST/NZDT instants, handled an omitted all=false jobs argument correctly, described a synthetic tool failure honestly, and delivered status through a complete isolated Coin turn in 8.94 seconds. Two same-prompt whole-reply samples took 9.52/11.40 seconds versus Qwen3.8's 24.38/24.80, with 170/227 versus 218/220 output words. Telegram/history were isolated and construction agents inactive. Cold scheduling took 24.82 seconds; these samples never established universal sub-15-second replies or model quality.

The actual knowledge-tool conversation exhausted its turn at 2026-10-16T01:11:15Z and retried; Telegram accepted message 975 at 01:20:40Z. Coin stayed active and pending input cleared after acceptance. The reliability owner holds this incident and the corrected finishing-tool menu. It is a concrete limit on the earlier short-fixture confidence, not proof that every delay is model-specific.

Evidence: /tmp/cointos-qwen35-coin-__efi1zs/{native-checks.json,gateway-check.json,turn-latency.json,health-after.json}; the native Coin service journal identifies the exhausted turn and accepted reply. Model facts and Gufo integration own the current shared-Qwen deployment; MiniCPM's owner retains its superseded trial.
