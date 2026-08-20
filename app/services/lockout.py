"""Attempt limiting for the PIN.

The PIN is four digits because it is typed on a kitchen wall with a child
standing next to it. That is the right trade for the setting and the wrong one
for a network: anything that can reach port 8600 can try all ten thousand of
them in well under a minute. Nothing else in this service stands between a
guesser and every write it protects, so the counting has to happen here.

**Counted per source address, deliberately.** The alternative is one counter
for the whole service, and it is worse in exactly the way that matters: any
device on the network could then lock the parent out of their own app by
guessing wrong five times on purpose, and there is nobody to appeal to. Per
source, a device that guesses wrong locks only itself, and the parent's phone
is unaffected by whatever the laptop in the next room is doing.

What that costs, stated plainly:

  - It buys less than it looks on the one surface that matters most. The
    kitchen wall screen is a single source used by the child and the parents
    both — it is where he claims and where they confirm — so "a guesser locks
    only itself" there means he locks his parents out of their own app. That
    is exactly the outcome per-source counting was meant to avoid, and it is
    why the first cooling-off is half a minute rather than five: on the shared
    screen the usual cause is a fat-finger or a bored nine-year-old, and
    neither should cost an evening.
  - An attacker with several devices, or one that can change its address, gets
    a fresh budget for each. On a home network that is a real limit but not an
    absolute one; it turns seconds into a long evening, which for a household
    pocket-money app is the point.
  - The address is the transport's, taken from the socket. Nothing the caller
    says about itself is used — not X-Forwarded-For, not a header, not a
    cookie — because a caller can claim to be anything, and a limiter keyed on
    a claim limits nobody.
  - Behind a reverse proxy, every request arrives from the proxy, so all
    callers share one bucket and this degrades to the global counter above,
    with the lockout risk that implies. If CoinQuest is ever put behind one,
    that is the moment to decide which proxy header can be trusted and to
    start reading it here. Until then it is served directly and this is right.

**The cooling-off escalates.** It starts at thirty seconds and doubles with
each consecutive lockout from the same source, up to a quarter of an hour, and
a correct PIN puts it back to the start. That shape is chosen for the two
populations who actually hit it. Somebody who mistyped waits half a minute and
gets on with their evening. Somebody working through the keyspace finds the
door closing harder each time: a flat five-minute cooling-off allows around
1,440 guesses a day from one address, which is the whole four-digit space
inside a week, while doubling to a fifteen-minute ceiling cuts the steady
state to roughly 480 a day.

The counters live in memory. The service keeps them for as long as it runs and
loses them on restart, which is acceptable: anybody who can restart the
container does not need to guess a PIN, and a lockout surviving a restart
would only strand the parent.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

logger = logging.getLogger("coinquest.authorisation")


class LockedOut(Exception):
    """Too many wrong PINs from this source. Carries how long is left."""

    def __init__(self, seconds_remaining: int) -> None:
        self.seconds_remaining = seconds_remaining
        super().__init__(describe_wait(seconds_remaining))


def describe_wait(seconds: int) -> str:
    """How long is left, in words a person would use.

    Told plainly, and on purpose. The likeliest victim of a lockout is a
    parent who mistyped in a hurry, and leaving them to guess whether the app
    is broken helps nobody. An attacker learns nothing from it that a clock
    would not tell them anyway.
    """
    if seconds <= 60:
        left = max(seconds, 1)
        unit = "second" if left == 1 else "seconds"
        return f"Too many incorrect PINs. Try again in {left} {unit}."
    minutes = (seconds + 59) // 60
    unit = "minute" if minutes == 1 else "minutes"
    return f"Too many incorrect PINs. Try again in about {minutes} {unit}."


@dataclass
class _Bucket:
    failures: int = 0
    locked_until: float = 0.0
    #: How many times in a row this source has been locked out. Survives a
    #: cooling-off expiring — otherwise the doubling would never happen, since
    #: every lockout would look like the first.
    lockouts: int = 0


@dataclass
class AttemptLimiter:
    """Consecutive failures per source, and a cooling-off once there are enough.

    A cooling-off rather than a lock: it clears itself with time, because there
    is no administrator in this house to unlock anything. Nothing has to be
    restarted, and nobody has to find a command.
    """

    limit: int
    #: The first cooling-off. Doubles on each consecutive lockout.
    cool_off_start_seconds: int
    #: The ceiling. Doubling stops here rather than growing without limit: an
    #: hours-long lockout punishes the household, not the guesser, who has
    #: nothing better to do anyway.
    cool_off_max_seconds: int
    #: Monotonic, so a clock change cannot shorten or extend a cooling-off.
    #: Injected in tests, so they need not wait in real time.
    clock: Callable[[], float] = time.monotonic
    _buckets: dict[str, _Bucket] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def cool_off_for(self, lockouts: int) -> int:
        """How long the nth consecutive lockout lasts.

        30, 60, 120, 240, 480, then the cap. Doubling rather than a fixed
        number because the first one should barely register and the tenth
        should be unmistakable.
        """
        if lockouts < 1:
            return 0
        doubled = self.cool_off_start_seconds * (2 ** (lockouts - 1))
        return min(doubled, self.cool_off_max_seconds)

    def check(self, source: str) -> None:
        """Refuse a source that is still cooling off.

        Called before the PIN is looked at, so a locked-out caller is refused
        whatever they send. A window that a correct guess could open early
        would not be a limit at all.
        """
        with self._lock:
            bucket = self._buckets.get(source)
            if bucket is None or not bucket.locked_until:
                return

            remaining = bucket.locked_until - self.clock()
            if remaining <= 0:
                # Served its time: the failure count starts again, but the
                # lockout count does not. Only a correct PIN clears that, so
                # somebody working through the keyspace cannot reset the
                # doubling simply by waiting each one out.
                bucket.failures = 0
                bucket.locked_until = 0.0
                return

        raise LockedOut(int(remaining) + 1)

    def record_failure(self, source: str) -> int:
        """Count a wrong PIN. Returns the consecutive count for this source."""
        with self._lock:
            bucket = self._buckets.setdefault(source, _Bucket())
            bucket.failures += 1
            count = bucket.failures
            cool_off = 0
            lockouts = bucket.lockouts

            if count >= self.limit:
                bucket.lockouts += 1
                lockouts = bucket.lockouts
                cool_off = self.cool_off_for(lockouts)
                bucket.locked_until = self.clock() + cool_off
                bucket.failures = 0

        # Logged so a burst is visible afterwards. There is no alerting here
        # and no one watching in real time; the log is the only way anybody
        # finds out this happened at all.
        if count >= self.limit:
            logger.warning(
                "PIN lockout: %s incorrect attempts from %s; refusing for %ss"
                " (lockout %s in a row from this source)",
                count,
                source,
                cool_off,
                lockouts,
            )
        else:
            logger.warning(
                "Incorrect PIN from %s (%s of %s before a cooling-off)",
                source,
                count,
                self.limit,
            )
        return count

    def record_success(self, source: str) -> None:
        """A correct PIN clears everything: the count and the escalation.

        The whole bucket goes. A household that mistypes, waits, and then gets
        in should not carry a longer punishment into next week.
        """
        with self._lock:
            self._buckets.pop(source, None)

    def seconds_remaining(self, source: str) -> int:
        with self._lock:
            bucket = self._buckets.get(source)
            if bucket is None or not bucket.locked_until:
                return 0
            return max(int(bucket.locked_until - self.clock()) + 1, 0)

    def reset(self) -> None:
        """Forget everything. For tests, and for nothing else."""
        with self._lock:
            self._buckets.clear()


_limiter: AttemptLimiter | None = None
_limiter_lock = threading.Lock()


def get_limiter() -> AttemptLimiter:
    global _limiter
    with _limiter_lock:
        if _limiter is None:
            from app.config import get_settings

            settings = get_settings()
            _limiter = AttemptLimiter(
                limit=settings.pin_attempt_limit,
                cool_off_start_seconds=settings.pin_cool_off_start_seconds,
                cool_off_max_seconds=settings.pin_cool_off_max_seconds,
            )
        return _limiter


def reset_limiter() -> None:
    """Drop the limiter so the next call rebuilds it from configuration."""
    global _limiter
    with _limiter_lock:
        _limiter = None
