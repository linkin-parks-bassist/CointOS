---
status: green
revised_at: "2026-11-16T13:49:50+11:00"
---

The Machine memory chart keeps its total equal to physical RAM and its Available segment equal to measured MemAvailable, clamped to that total. All recipe GB estimates convert to GiB before joining measured values. Model weights and KV-cache are labeled estimates. Their combined estimate is bounded by measured used memory after saved contexts; the remaining used portion is labeled Other used. Reclaimable model mappings are already represented in MemAvailable, so nominal weights must not be added again to total physical usage. Saved-context bytes are measured, bounded to current use. Recipe estimates cannot establish a precise OS/model split.

web/dashboard.html owns memoryValues/renderMemory. tests.test_dashboard_transport covers anonymous/file-backed models, decimal/binary unit conversion, the Flash-Next case that formerly displayed 168 GB on a 128-GiB machine, and estimates exceeding measured use.

Proof:

```bash
python3 -m unittest tests.test_dashboard_transport.DashboardTransport.test_memory_chart_counts_weights_once_for_each_backing_type
```
