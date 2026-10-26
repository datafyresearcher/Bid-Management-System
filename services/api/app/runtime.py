"""How much of the current request is left.

A serverless instance is given a hard limit on how long one request may
take — sixty seconds here. Every phase of a request draws from the same
budget: reading a portal, writing what it found, scoring it, and asking the
model to explain it.

That matters because the phases are not independent. A request that starts
slowly — a cold instance that has to boot and populate before it serves
anything — has less time left for the work the user actually asked for. With
one budget, a slow start means less is done rather than the request running
past the end of its time and being reported as a failure.

The deadline is set by the middleware for the request being served and is
read by the parts of the system that do the work.
"""

import time
from contextvars import ContextVar

_DEADLINE = ContextVar("bms_request_deadline", default=None)

# What the instance did before it served anything. It is charged to the
# first request the instance handles, and to no other.
_STARTUP_SECONDS = {"value": 0.0}


def set_startup_seconds(value):
    """Record how long the instance took to get ready."""
    _STARTUP_SECONDS["value"] = float(value or 0.0)


def claim_startup_seconds():
    """The start-up cost of this instance, charged once, to the first request."""
    value = _STARTUP_SECONDS["value"]
    _STARTUP_SECONDS["value"] = 0.0
    return value


def set_deadline(value):
    _DEADLINE.set(value)


def deadline():
    """The absolute time this request runs out at, or None when untimed."""
    return _DEADLINE.get()


def remaining(default=None):
    """Seconds left in this request.

    ``None`` means nothing is being timed, and the caller should use its own
    budget.
    """
    value = _DEADLINE.get()
    if value is None:
        return default
    return value - time.monotonic()
