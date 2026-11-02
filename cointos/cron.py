"""Five-field cron expressions evaluated against a named timezone's wall clock.

A wall-clock time skipped by a daylight-saving change runs just after the change; one repeated
by a change runs once, at its first occurrence.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

FIELDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
MONTHS = dict(zip('jan feb mar apr may jun jul aug sep oct nov dec'.split(), range(1, 13)))
DAYS = dict(zip('sun mon tue wed thu fri sat'.split(), range(7)))
NAMES = ({}, {}, {}, MONTHS, DAYS)
# Longer than any gap between leap days, including a skipped century leap year.
HORIZON_DAYS = 366 * 9


def _value(text: str, names: dict) -> int:
    text = text.lower()
    if text in names:
        return names[text]
    if not text.isascii() or not text.isdigit():
        raise ValueError(f'invalid cron value {text!r}')
    return int(text)


def _field(text: str, low: int, high: int, names: dict) -> set[int]:
    values = set()
    for part in text.split(','):
        span, slash, step = part.partition('/')
        if slash and (not step.isascii() or not step.isdigit() or int(step) < 1):
            raise ValueError(f'invalid cron step {part!r}')
        if span == '*':
            start, stop = low, high
        elif '-' in span:
            first, _, last = span.partition('-')
            start, stop = _value(first, names), _value(last, names)
        else:
            start = _value(span, names)
            stop = high if slash else start
        if not low <= start <= stop <= high:
            raise ValueError(f'cron field {part!r} is outside {low}-{high}')
        values.update(range(start, stop + 1, int(step) if slash else 1))
    return values


def parse(expression: str) -> tuple[set[int], ...]:
    if not isinstance(expression, str) or len(expression.split()) != 5:
        raise ValueError('cron must have five fields: minute hour day-of-month month day-of-week')
    return tuple(_field(text, *bounds, names)
                 for text, bounds, names in zip(expression.split(), FIELDS, NAMES))


def _day_matches(expression: str, fields: tuple, day) -> bool:
    _, _, dom_text, _, dow_text = expression.split()
    _, _, dom, months, dow = fields
    if day.month not in months:
        return False
    in_month, in_week = day.day in dom, (day.isoweekday() % 7 in dow or (day.isoweekday() == 7 and 7 in dow))
    # Standard cron: when both day fields are restricted, either one matching is enough.
    if not dom_text.startswith('*') and not dow_text.startswith('*'):
        return in_month or in_week
    return in_month and in_week


def after(expression: str, timezone: str, instant: float) -> float:
    """The first matching instant strictly later than `instant`."""
    fields = parse(expression)
    zone = ZoneInfo(timezone)
    minutes, hours = sorted(fields[0]), sorted(fields[1])
    day = datetime.fromtimestamp(instant, zone).date()
    for offset in range(HORIZON_DAYS):
        current = day + timedelta(days=offset)
        if not _day_matches(expression, fields, current):
            continue
        for hour in hours:
            for minute in minutes:
                candidate = datetime(current.year, current.month, current.day, hour, minute, tzinfo=zone).timestamp()
                if candidate > instant:
                    return candidate
    raise ValueError(f'cron {expression!r} never matches')
