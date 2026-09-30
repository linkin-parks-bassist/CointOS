---
status: green
revised_at: "2026-09-29T08:03:58+10:00"
---

In the Work panel heading, the scout control is a right-aligned flex row ordered as status text followed by the `Spawn scout` button. Because the control has `margin-left: auto` and the button is its last child, status messages such as “Scout scheduled” grow into the space on the button's left while the button remains fixed at the panel's right edge. Source and installed copies are `web/dashboard.html` and `~/.CointOS/web/dashboard.html`.
