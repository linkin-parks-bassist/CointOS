---
status: green
revised_at: "2026-10-18T22:33:27+11:00"
---

Legacy llama.cpp target-only snapshots lack draft history; loading the paired-MTP snapshot patch cannot reconstruct it. That patch is installed and a managed paired restore is verified. When using the llama MTP path, a target-only cache remains useful while fresh decoding accumulates draft context; sustained workload gains remain unmeasured.

Production construction Qwen now uses Gufo DFlash2 decoding. Gufo has its own snapshot ABI and directory and cannot reuse either llama format or Gufo AR snapshots. Its backend migration invalidates incompatible Qwen cache entries while preserving conversation history; what/is/the/gufo/backend/candidate/for/cointos.md owns deployment details.
