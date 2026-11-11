"""Minimal 5-field cron matcher (UTC) for monitoring report schedules. Owner: A4.

Supports ``*``, numbers, ranges ``a-b``, steps ``*/n`` and ``a-b/n``, and comma lists, in the order
minute hour day-of-month month day-of-week (0 or 7 = Sunday). As in classic cron, when both day-of-month and
day-of-week are restricted a day matches if either does. No dependency: the schedules are simple and the timer
that checks them runs hourly.
"""

from __future__ import annotations

from datetime import datetime, timedelta

_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
#: never scan more than this many minutes (a weekly schedule needs at most 7 days)
MAX_SCAN_MINUTES = 40 * 24 * 60


def _field(text: str, low: int, high: int) -> set[int]:
    values: set[int] = set()
    for part in text.split(","):
        base, _, step_text = part.partition("/")
        step = int(step_text) if step_text else 1
        if step < 1:
            raise ValueError(f"bad cron step in {part!r}")
        if base == "*":
            start, end = low, high
        elif "-" in base:
            a, b = base.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = int(base)
            end = high if step_text else start
        if not (low <= start <= end <= high):
            raise ValueError(f"cron value {part!r} outside {low}-{high}")
        values.update(range(start, end + 1, step))
    return values


class Cron:
    def __init__(self, expr: str) -> None:
        fields = expr.split()
        if len(fields) != 5:
            raise ValueError("cron must have 5 fields: minute hour day-of-month month day-of-week")
        sets = [_field(f, low, high) for f, (low, high) in zip(fields, _RANGES, strict=True)]
        self.minutes, self.hours, self.days, self.months, dow = sets
        self.weekdays = {d % 7 for d in dow}  # 7 -> 0 (Sunday)
        self.dom_any, self.dow_any = fields[2] == "*", fields[4] == "*"

    def matches(self, at: datetime) -> bool:
        if at.minute not in self.minutes or at.hour not in self.hours or at.month not in self.months:
            return False
        dom = at.day in self.days
        dow = (at.isoweekday() % 7) in self.weekdays  # Monday=1 ... Sunday=0
        if self.dom_any or self.dow_any:
            return dom and dow
        return dom or dow


def fired_between(expr: str, start: datetime, end: datetime) -> bool:
    """True if the schedule fired at a whole minute in (start, end]."""
    cron = Cron(expr)
    at = start.replace(second=0, microsecond=0) + timedelta(minutes=1)
    stop = min(end, start + timedelta(minutes=MAX_SCAN_MINUTES))
    while at <= stop:
        if cron.matches(at):
            return True
        at += timedelta(minutes=1)
    return False
