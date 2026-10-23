"""One-pole telemetry filters driven only by time spent in their own phase.

Callers hold the daemon lock. Inactive phases hold their values; restart resets them.
"""
import math

TIME_CONSTANT = 10.0
FILTERS = {}


def _smooth(name, value, seconds):
    previous = FILTERS.get(name)
    alpha = -math.expm1(-seconds / TIME_CONSTANT)
    FILTERS[name] = value if previous is None else previous + alpha * (value - previous)


def record(kind, tokens, seconds, *, draft_tokens=0, accepted_tokens=0):
    if seconds <= 0:
        return
    _smooth(kind, tokens / seconds, seconds)
    if kind == 'generation' and draft_tokens > 0:
        # Smooth matching proposal/acceptance rates, not unweighted percentages.
        _smooth('draft', draft_tokens / seconds, seconds)
        _smooth('accepted', accepted_tokens / seconds, seconds)


def snapshot():
    drafted = FILTERS.get('draft')
    return {'smoothing_active_seconds': TIME_CONSTANT,
            'generation_tps': FILTERS.get('generation'),
            'prefill_tps': FILTERS.get('prefill'),
            'mtp_acceptance': 100 * FILTERS['accepted'] / drafted if drafted else None}
