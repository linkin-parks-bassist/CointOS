---
status: green
revised_at: "2026-10-15T06:50:19+11:00"
---

LFM2.5-24B-A2B Q4_K_M is installed in Lemonade as LFM2.5-24B-A2B-GGUF-Q4_K_M, alias CointOS-LFM25-Trial. LFM's raw speed did not offset weaker coding results and longer attempts in this small trial. It remains unloaded. The trial restored MiniCPM successfully; the user's subsequent production choice is Qwen3.8-27B, owned by what/are/the/model/facts.md. These fixtures did not test manager/reviewer reliability.

Official checkpoint LiquidAI/LFM2.5-24B-A2B-GGUF, revision 0912d33141f77e10705345a6732bfd83f0252fdc; advertised size 14,526,258,464 bytes and SHA256 d3334405b96228eb9908cdebb5c6194908f2da64282bda852afc3a3910c64e7d. No independent local checksum was computed. [Official card](https://huggingface.co/LiquidAI/LFM2.5-24B-A2B-GGUF).

Both used existing Vulkan, Q4_K_M, one 131072-token lane without speculation, temperature .1/top-k 50/top-p .95/min-p .05/repeat penalty 1.05. Coding used native reasoning cap 384, 2048 tokens/reply, 18 rounds/12000 generated tokens/600 seconds per case. Trial sampling differs from MiniCPM production sampling.

Six isolated Python/JavaScript repairs covered UTF8 framing, dependency graphs, revision preservation, atomic JSON, SQLite transfers and async retry. Three seeds/case yielded 18 outputs/model. Typed read/write/test/finish tools constrained implementation edits. Saved source was independently replayed under five Python hash seeds without stale bytecode.

Consistent code passes: MiniCPM 15/18, LFM 4/18. Mini passed every case except graphs; LFM passed one graph, two atomic and one transfer output. Mini graph code had hash-sensitive recursion failures despite terminal acceptance. LFM often repeated basic tests or claimed completion without terminal validation. Terminal submissions accepted 17/18 versus 3/18; a saved passing artifact can lack submission. Median attempt wall time was 43.0 versus 75.9 seconds; total 16.9 versus 22.1 minutes. These include failures/round limits, not time to correct answers. This small synthetic harness is not a general coding or autonomous-system benchmark.

Median decode, three cold 256-token samples:
- Mini prompt 2272 tokens: 52.7 tok/s; LFM 2190: 88.8.
- Mini 18232: 48.1; LFM 17580: 76.1.
- Mini 50432: 41.7; LFM 48630: 58.2.

Median prefill was 351–383 versus 413–436 tok/s. Text was approximately matched; tokenizer lengths differ. Raw gain is 1.4–1.7×, without 128k/useful-autonomy extrapolation.

Reviewable evidence: /tmp/cointos-lfm25-trial/report.txt, results.json, replay.json, bench.py, fixtures.py and candidates. The controller exited nonzero only on its immediate final transient-PSI check after trials/restoration; later all ten checks passed. No managed-product source/tests were benchmark edits.

Native LFM typed calls and multi-turn coding worked. CointOS custom token-renderer/tool transport and continuation compatibility remain unverified before adoption.
