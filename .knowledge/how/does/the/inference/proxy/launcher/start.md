---
status: green
revised_at: "2026-09-14T23:49:51+10:00"
---

scripts/inference_proxy is a shell wrapper that resolves the installation root, changes there and executes python3 -m ecosystem.inference_proxy with forwarded arguments. The module supports --help and otherwise reads config/model-policy.json inference_proxy policy and serves with a monotonic clock. This repairs the Python-file launcher import failure outside the package context without relying on inherited PYTHONPATH. Executing the absolute wrapper with --help from /tmp passed without starting a server. services/systemd/agent-inference-proxy.service is the service template; installer rewrites checkout paths to the installed prefix. Installed deployment and live service qualification remain separate checks.
