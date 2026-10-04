"""Tests never touch real runtime state: the ledger, keys and journal go to a temporary directory."""
import os
import tempfile

os.environ["COINTOS_STATE"] = tempfile.mkdtemp(prefix="cointos-test-state-")
