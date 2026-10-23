"""Tests use disposable runtime state, generated knowledge and registry paths."""
import os
import sys
import tempfile
from pathlib import Path

if 'cointos.config' in sys.modules:
    raise RuntimeError('Import tests before cointos modules: runtime paths are captured at import time; '
                       'late test isolation would write fixture events into the live runtime.')

os.environ["COINTOS_STATE"] = tempfile.mkdtemp(prefix="cointos-test-state-")
_state = Path(os.environ["COINTOS_STATE"])
os.environ["KT_CONFIG"] = str(_state / "kt/roots.json")
os.environ["KT_GLOBAL_ROOT"] = str(_state / "kt/global")
os.environ["KT_REWRITE_STATE_DIR"] = str(_state / "kt/rewrites")

from cointos import queues, state

# Startup/cache reconciliation can run even in a failing regression. Isolate its
# filesystem roots for the entire suite, rather than relying on per-test mocks.
state.CONFIG["snapshots"] = str(_state / "memory-snapshots")
state.CONFIG["disk_snapshots"] = str(_state / "disk-snapshots")
# A real API mutation may publish without support.quiet(). Its generated view and
# kt registration must be isolated just like the authoritative ledger it projects.
queues.ROOT = _state / "runtime"
(queues.ROOT / ".knowledge").mkdir(parents=True)
