"""Cooperative time budget for one staff browser request."""
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic

_deadline = ContextVar("omnixat_staff_deadline", default=None)


def staff_seconds_left(cap):
    deadline = _deadline.get()
    if deadline is None:
        return cap
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise TimeoutError("Staff request budget exhausted")
    return min(cap, remaining)


@contextmanager
def staff_request_budget(seconds):
    deadline = monotonic() + staff_seconds_left(seconds)
    token = _deadline.set(deadline)
    try:
        yield
    finally:
        _deadline.reset(token)
