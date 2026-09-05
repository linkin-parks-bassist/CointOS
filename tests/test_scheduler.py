import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ecosystem.scheduler import choose, priority

REPO = Path(__file__).resolve().parents[1]


def scheduling_policy():
    values = json.loads((REPO / "config/scheduling.json").read_text(encoding="utf-8"))
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"),
                           allow_nan=False).encode("utf-8")
    return {"schema_version": 1, "values": values,
            "digest": hashlib.sha256(canonical).hexdigest(),
            "activated_at": "2026-09-05T00:00:00+00:00",
            "source_path": "config/scheduling.json"}


def make_job(job_id, model, created_at, **extra):
    job = {"id": job_id, "model": model, "created_at": created_at,
           "authority_profile": "worker", "kind": "agent-task", "state": "ready"}
    job.update(extra)
    return job


def inventory(loaded_ids=()):
    return {"models": [
        {"id": "large", "size_gb": 16, "loaded": "large" in loaded_ids},
        {"id": "small", "size_gb": 4, "loaded": "small" in loaded_ids},
    ]}


def test_scheduler_consumes_effective_priority():
    now = datetime.now(timezone.utc)
    doc = scheduling_policy()
    fresh = make_job("a", "small", now.isoformat(), role="unheard_of_role")
    ancient = make_job("b", "small",
                       (now - timedelta(seconds=10**9)).isoformat(),
                       role="unheard_of_role")
    assert priority(fresh, doc, now) == 250
    assert priority(ancient, doc, now) == 699
    coin = make_job("c", "large", now.isoformat(), authority_profile="coin")
    path, chosen, _ = choose([(Path("a"), fresh), (Path("c"), coin)],
                             inventory(), doc, now)
    assert path == Path("c")
    assert chosen["id"] == "c"


def test_survivor_preempts_work_without_starving_coin():
    now = datetime.now(timezone.utc)
    doc = scheduling_policy()
    coin_ancient = make_job("coin", "small",
                            (now - timedelta(seconds=10**9)).isoformat(),
                            authority_profile="coin")
    survivor_fresh = make_job("survivor", "large", now.isoformat(),
                              authority_profile="sole_survivor")
    assert priority(coin_ancient, doc, now) == 999
    assert priority(survivor_fresh, doc, now) == 1000
    path, chosen, _ = choose([(Path("coin"), coin_ancient),
                              (Path("survivor"), survivor_fresh)],
                             inventory(), doc, now)
    assert path == Path("survivor")
    coin_fresh = make_job("coin2", "small", now.isoformat(),
                          authority_profile="coin")
    worker_ancient = make_job("worker", "large",
                              (now - timedelta(seconds=10**9)).isoformat())
    path, chosen, _ = choose([(Path("coin2"), coin_fresh),
                              (Path("worker"), worker_ancient)],
                             inventory(), doc, now)
    assert path == Path("coin2")


def test_short_jobs_rotate_without_starvation():
    now = datetime.now(timezone.utc)
    doc = scheduling_policy()
    old_coder = make_job("old", "small", (now - timedelta(minutes=30)).isoformat(),
                         role="coder")
    new_coder = make_job("new", "small", now.isoformat(), role="coder")
    assert priority(old_coder, doc, now) == 580
    assert priority(new_coder, doc, now) == 550
    path, chosen, _ = choose([(Path("new"), new_coder),
                              (Path("old"), old_coder)],
                             inventory(), doc, now)
    assert path == Path("old")
    assert chosen["id"] == "old"


def test_resident_model_batching_breaks_ties():
    now = datetime.now(timezone.utc)
    doc = scheduling_policy()
    on_resident = make_job("a", "large", now.isoformat())
    on_switch = make_job("b", "small", now.isoformat())
    path, _, reason = choose([(Path("b"), on_switch), (Path("a"), on_resident)],
                             inventory(loaded_ids=("large",)), doc, now)
    assert path == Path("a")
    assert "batching" in reason


def load_tests(_loader, _tests, _pattern):
    return unittest.TestSuite((
        unittest.FunctionTestCase(test_scheduler_consumes_effective_priority),
        unittest.FunctionTestCase(test_survivor_preempts_work_without_starving_coin),
        unittest.FunctionTestCase(test_short_jobs_rotate_without_starvation),
        unittest.FunctionTestCase(test_resident_model_batching_breaks_ties),
    ))
