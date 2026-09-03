# Reconcile the local model catalogue

Compare Lemonade's live registry, downloaded files, loaded backends, executor model
configuration, role preferences, and scheduling policy. Investigate newly available
or newly downloaded models for capabilities, architecture/tool compatibility,
context limits, quantization footprint, measured memory headroom, and likely task
fit. Integrate suitable models through the shared catalogue and routing policy;
never hardcode a task-specific choice in unrelated code.

Downloading is not proof of runnability. Perform a bounded smoke test before giving
a model consequential work, record degraded constraints honestly, and avoid loading
a near-capacity model beside incompatible residents. Conversely, local compute has
no marginal monetary cost: do not undersize reasoning merely to save imaginary
money. Preserve responsive control capacity, amortize expensive loads, and prefer
longer residency for large models. Report only decisions or failures David needs.
