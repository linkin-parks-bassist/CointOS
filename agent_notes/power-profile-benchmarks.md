# Local inference power-profile benchmarks

Recorded by the root Codex agent on 2026-09-04. LED colour names are David's
physical observations; Linux reported `performance` for orange, yellow, blue, and
purple, so the button appears to control firmware behavior below that interface.

## Controlled protocol

- Backend: Qwen3.6-35B-A3B-MTP GGUF, Q4_K_XL, Vulkan llama.cpp
- Context capacity: 131072
- Endpoint: llama.cpp `/completion`
- Input: 36 tokens, fixed numbered-list prompt
- Output: 512 tokens, stopped at the requested limit
- Decoding: temperature 0, seed 1, prompt cache disabled
- Compare `timings.predicted_per_second`; repeat the identical request for every
  colour after the machine settles.

## Controlled results

| LED colour | Generated tokens/s | Prompt tokens/s | Notes |
|---|---:|---:|---|
| Purple | 81.87, 83.68, 81.42 | 108.69, 223.15, 221.26 | Mean generation 82.32 tokens/s; Linux profile `performance`. |
| Orange | 82.98, 83.21, 85.08 | 222.41, 218.38, 215.31 | Mean generation 83.76 tokens/s; about 1.7% above purple, with much greater fan noise. |

## Opportunistic observations (not directly comparable)

| LED colour | Observed tokens/s | Notes |
|---|---:|---|
| Orange | 8.29 | Live agent generation with long retained context; loud fan. |
| Yellow | 33.56 | Different live-agent window; much quieter. |
| Blue | — | No active generation window captured. |

The opportunistic values must not be used to rank profiles. Long-context prompt
evaluation, speculative-decoding acceptance, tool pauses, and output structure were
not controlled. Only the controlled table supports colour-to-colour comparison.
