"""Dates, weeks and months, resolved in an explicitly supplied timezone.

The container clock is UTC. Nothing here reads the system zone, and nothing
takes a default one: every function that has to know what "today" means, or
where a day begins, is given the zone by its caller. Getting this wrong shows
up as a chore filed to the wrong week for one hour a night through the summer,
which is precisely the sort of bug nobody notices until settlement.

The chore week runs Sunday to Saturday inclusive. Both British clock changes
happen on a Sunday — at 01:00 GMT in spring and 02:00 BST in autumn — so a
London week boundary at midnight is never ambiguous and never skipped. A week
is not always 168 hours long, though, which is why intervals are computed from
the instants below rather than by adding seven days to a start.

Intervals are half-open: [start, end). The end is the first instant of the
next period, not the last instant of this one. A "last instant" only exists at
whatever resolution you happen to be using, and comparing against it is how
something recorded at 23:59:59.7 falls out of the week that owns it.

One trap to know about, because it bites silently. When two aware datetimes
share the same tzinfo object, Python subtracts them by wall clock and ignores
the zone entirely, so the week containing a clock change comes out as exactly
168 hours. Use `elapsed()` for any duration spanning days. Comparisons are
unaffected in practice: wall-clock ordering is the right answer to "which
local day is this in", and no London boundary falls inside a repeated hour.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo

# date.weekday() counts from Monday; the chore week starts on Sunday.
_SUNDAY = 6
DAYS_IN_WEEK = 7


def elapsed(start: datetime, end: datetime) -> timedelta:
    """Real time between two instants, via UTC.

    Subtracting the datetimes directly gives the wall-clock difference when
    they share a tzinfo object, which is an hour out across a clock change.
    """
    return end.astimezone(timezone.utc) - start.astimezone(timezone.utc)


def start_of_day(day: date, tz: tzinfo) -> datetime:
    """The first instant of a local calendar day.

    London never skips midnight, but a zone that did would make the naive
    midnight below a time that did not happen. Rather than let the standard
    library silently invent an offset for it, step forward to the first
    instant that genuinely exists on that day.
    """
    candidate = datetime.combine(day, time.min, tzinfo=tz)
    if candidate.astimezone(tz).date() == day:
        return candidate

    for minutes in range(1, 24 * 60):
        shifted = datetime.combine(day, time.min, tzinfo=tz) + timedelta(minutes=minutes)
        if shifted.astimezone(tz).date() == day:
            return shifted
    raise ValueError(f"{day} does not occur in {tz}.")


def local_date(instant: datetime, tz: tzinfo) -> date:
    """The calendar day an instant falls in, seen from `tz`.

    A naive datetime is rejected: an instant with no zone is not an instant,
    and assuming one is how UTC leaks in.
    """
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("An instant must carry a timezone.")
    return instant.astimezone(tz).date()


def today(tz: tzinfo) -> date:
    """The current local day. The only place 'now' enters this module."""
    return datetime.now(tz).date()


@dataclass(frozen=True)
class Period:
    """A run of whole local days, half-open in time.

    `start` and `end` are the first and last days inclusive, as a person would
    describe them. `starts_at` and `ends_before` are the instants that bound
    it, and are what a query should compare against.
    """

    start: date
    end: date
    tz: tzinfo

    @property
    def starts_at(self) -> datetime:
        return start_of_day(self.start, self.tz)

    @property
    def ends_before(self) -> datetime:
        """The first instant of the day after this period ends."""
        return start_of_day(self.end + timedelta(days=1), self.tz)

    @property
    def duration(self) -> timedelta:
        """How long the period actually lasts. 169 hours in a week that gains
        an hour to GMT, 167 in the one that loses it to BST."""
        return elapsed(self.starts_at, self.ends_before)

    @property
    def days(self) -> list[date]:
        span = (self.end - self.start).days + 1
        return [self.start + timedelta(days=offset) for offset in range(span)]

    def contains(self, instant: datetime) -> bool:
        return self.starts_at <= instant.astimezone(self.tz) < self.ends_before

    def contains_day(self, day: date) -> bool:
        return self.start <= day <= self.end

    def __str__(self) -> str:
        return f"{self.start.isoformat()}..{self.end.isoformat()}"


def week_start(day: date) -> date:
    """The Sunday that opens the chore week containing `day`."""
    return day - timedelta(days=(day.weekday() - _SUNDAY) % DAYS_IN_WEEK)


def week_containing(day: date, tz: tzinfo) -> Period:
    """The Sunday-to-Saturday chore week a local day belongs to."""
    start = week_start(day)
    return Period(start=start, end=start + timedelta(days=DAYS_IN_WEEK - 1), tz=tz)


def week_containing_instant(instant: datetime, tz: tzinfo) -> Period:
    """The chore week an instant belongs to, decided by its local day."""
    return week_containing(local_date(instant, tz), tz)


def current_week(tz: tzinfo) -> Period:
    return week_containing(today(tz), tz)


def day_containing(day: date, tz: tzinfo) -> Period:
    """A single local day as a period, for the same treatment as a week."""
    return Period(start=day, end=day, tz=tz)


def month_containing(day: date, tz: tzinfo) -> Period:
    """The calendar month a local day belongs to, first day to last."""
    start = day.replace(day=1)
    return Period(start=start, end=_last_day_of_month(start), tz=tz)


def month_bounds(year: int, month: int, tz: tzinfo) -> tuple[datetime, datetime]:
    """A month's opening instant and the instant it ends before."""
    period = month_containing(date(year, month, 1), tz)
    return period.starts_at, period.ends_before


def _last_day_of_month(day: date) -> date:
    """The last day of `day`'s month, found by stepping back from the next."""
    if day.month == 12:
        first_of_next = date(day.year + 1, 1, 1)
    else:
        first_of_next = date(day.year, day.month + 1, 1)
    return first_of_next - timedelta(days=1)
