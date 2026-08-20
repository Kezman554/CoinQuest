"""Weeks and months in Europe/London, including both clock changes.

Every case passes the zone explicitly. Nothing here depends on the machine's
timezone, so these pass identically on a UTC container and a British laptop.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.services.calendar import (
    Period,
    current_week,
    day_containing,
    elapsed,
    local_date,
    month_bounds,
    month_containing,
    start_of_day,
    today,
    week_containing,
    week_containing_instant,
    week_start,
)

LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")
UTC = timezone.utc


def hours(period: Period) -> int:
    assert period.duration % timedelta(hours=1) == timedelta(0)
    return period.duration // timedelta(hours=1)


# --- The week runs Sunday to Saturday -------------------------------------


@pytest.mark.parametrize(
    ("day", "expected_sunday"),
    [
        ("2026-08-16", "2026-08-16"),  # a Sunday is its own week start
        ("2026-08-17", "2026-08-16"),  # Monday
        ("2026-08-20", "2026-08-16"),  # Thursday
        ("2026-08-22", "2026-08-16"),  # Saturday, the last day
        ("2026-08-23", "2026-08-23"),  # the next Sunday opens the next week
    ],
)
def test_week_start_is_the_preceding_sunday(day, expected_sunday):
    assert week_start(date.fromisoformat(day)) == date.fromisoformat(expected_sunday)


def test_a_week_runs_sunday_to_saturday_inclusive():
    week = week_containing(date(2026, 8, 20), LONDON)
    assert (week.start, week.end) == (date(2026, 8, 16), date(2026, 8, 22))
    assert week.start.strftime("%A") == "Sunday"
    assert week.end.strftime("%A") == "Saturday"
    assert len(week.days) == 7


def test_a_saturday_and_the_sunday_after_are_different_weeks():
    saturday = week_containing(date(2026, 8, 22), LONDON)
    sunday = week_containing(date(2026, 8, 23), LONDON)
    assert saturday != sunday
    assert saturday.ends_before == sunday.starts_at


# --- The BST to GMT week --------------------------------------------------


def test_the_week_that_gains_an_hour_is_169_hours_long():
    # Clocks go back at 02:00 BST on Sunday 25 October 2026 - the very day the
    # week opens. The week is an hour longer than seven times twenty-four.
    week = week_containing(date(2026, 10, 25), LONDON)
    assert (week.start, week.end) == (date(2026, 10, 25), date(2026, 10, 31))
    assert hours(week) == 169
    assert len(week.days) == 7


def test_the_week_that_loses_an_hour_is_167_hours_long():
    # Clocks go forward at 01:00 GMT on Sunday 29 March 2026.
    week = week_containing(date(2026, 3, 29), LONDON)
    assert hours(week) == 167
    assert len(week.days) == 7


def test_the_transition_week_opens_in_bst_and_closes_in_gmt():
    week = week_containing(date(2026, 10, 25), LONDON)
    assert week.starts_at.utcoffset() == timedelta(hours=1)   # BST
    assert week.ends_before.utcoffset() == timedelta(0)       # GMT
    assert week.starts_at.isoformat() == "2026-10-25T00:00:00+01:00"
    assert week.ends_before.isoformat() == "2026-11-01T00:00:00+00:00"


def test_both_repeated_local_hours_belong_to_the_same_week():
    # 01:30 happens twice on the morning the clocks go back. Both are Sunday,
    # and both belong to the week that Sunday opens.
    first = datetime(2026, 10, 25, 1, 30, tzinfo=LONDON, fold=0)
    second = datetime(2026, 10, 25, 1, 30, tzinfo=LONDON, fold=1)
    assert elapsed(first, second) == timedelta(hours=1)
    for instant in (first, second):
        assert week_containing_instant(instant, LONDON).start == date(2026, 10, 25)


def test_a_chore_late_at_night_belongs_to_the_british_day():
    # The container clock is UTC. Through the summer, 23:30 UTC is already
    # tomorrow in London, and the week boundary has to follow London.
    late_saturday_utc = datetime(2026, 8, 22, 23, 30, tzinfo=UTC)
    assert local_date(late_saturday_utc, LONDON) == date(2026, 8, 23)
    assert local_date(late_saturday_utc, UTC) == date(2026, 8, 22)

    # Which puts it in the new week in London, and the old one in UTC.
    assert week_containing_instant(late_saturday_utc, LONDON).start == date(2026, 8, 23)
    assert week_containing_instant(late_saturday_utc, UTC).start == date(2026, 8, 16)


def test_the_end_instant_is_excluded_and_the_start_included():
    week = week_containing(date(2026, 10, 25), LONDON)
    assert week.contains(week.starts_at)
    assert not week.contains(week.ends_before)
    assert week.contains(week.ends_before - timedelta(microseconds=1))


# --- A week spanning a month end ------------------------------------------


def test_a_week_may_span_a_month_end():
    week = week_containing(date(2026, 8, 31), LONDON)
    assert (week.start, week.end) == (date(2026, 8, 30), date(2026, 9, 5))
    assert week.contains_day(date(2026, 8, 31))
    assert week.contains_day(date(2026, 9, 1))
    assert hours(week) == 168


def test_a_week_may_span_a_year_end():
    week = week_containing(date(2026, 12, 31), LONDON)
    assert (week.start, week.end) == (date(2026, 12, 27), date(2027, 1, 2))
    assert hours(week) == 168


def test_a_week_spanning_a_month_end_splits_across_two_months():
    week = week_containing(date(2026, 8, 31), LONDON)
    august = month_containing(date(2026, 8, 31), LONDON)
    september = month_containing(date(2026, 9, 1), LONDON)
    in_august = [day for day in week.days if august.contains_day(day)]
    in_september = [day for day in week.days if september.contains_day(day)]
    assert len(in_august) == 2      # Sunday 30th, Monday 31st
    assert len(in_september) == 5
    assert august.ends_before == september.starts_at


# --- Months ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "first", "last"),
    [
        ("2026-08-20", "2026-08-01", "2026-08-31"),
        ("2026-02-14", "2026-02-01", "2026-02-28"),
        ("2028-02-14", "2028-02-01", "2028-02-29"),  # leap year
        ("2026-12-25", "2026-12-01", "2026-12-31"),
        ("2026-04-30", "2026-04-01", "2026-04-30"),
    ],
)
def test_month_containing(day, first, last):
    month = month_containing(date.fromisoformat(day), LONDON)
    assert month.start == date.fromisoformat(first)
    assert month.end == date.fromisoformat(last)


def test_month_bounds_are_local_instants():
    starts_at, ends_before = month_bounds(2026, 10, LONDON)
    assert starts_at.isoformat() == "2026-10-01T00:00:00+01:00"    # BST
    assert ends_before.isoformat() == "2026-11-01T00:00:00+00:00"  # GMT
    assert elapsed(starts_at, ends_before) == timedelta(days=31, hours=1)


def test_december_rolls_into_january():
    starts_at, ends_before = month_bounds(2026, 12, LONDON)
    assert starts_at.date() == date(2026, 12, 1)
    assert ends_before.date() == date(2027, 1, 1)


# --- Days and explicit zones ----------------------------------------------


def test_a_day_is_a_period_of_one_day():
    day = day_containing(date(2026, 8, 20), LONDON)
    assert day.days == [date(2026, 8, 20)]
    assert hours(day) == 24


def test_the_days_the_clocks_change_are_25_and_23_hours():
    assert hours(day_containing(date(2026, 10, 25), LONDON)) == 25
    assert hours(day_containing(date(2026, 3, 29), LONDON)) == 23


def test_the_zone_is_the_callers_and_never_the_systems():
    instant = datetime(2026, 8, 23, 2, 30, tzinfo=UTC)
    assert local_date(instant, LONDON) == date(2026, 8, 23)
    assert local_date(instant, NEW_YORK) == date(2026, 8, 22)
    assert week_containing_instant(instant, LONDON).start == date(2026, 8, 23)
    assert week_containing_instant(instant, NEW_YORK).start == date(2026, 8, 16)


def test_a_naive_datetime_is_refused():
    with pytest.raises(ValueError):
        local_date(datetime(2026, 8, 20, 12, 0), LONDON)


def test_start_of_day_is_local_midnight():
    summer = start_of_day(date(2026, 8, 20), LONDON)
    winter = start_of_day(date(2026, 1, 20), LONDON)
    assert summer.isoformat() == "2026-08-20T00:00:00+01:00"
    assert winter.isoformat() == "2026-01-20T00:00:00+00:00"


def test_today_and_current_week_agree():
    now = today(LONDON)
    week = current_week(LONDON)
    assert week.contains_day(now)
    assert week.start == week_start(now)


def test_elapsed_survives_the_shared_tzinfo_trap():
    # Subtracting these directly gives 168 hours, because Python compares the
    # wall clocks when the tzinfo objects match. This is the whole reason
    # elapsed() exists.
    start = start_of_day(date(2026, 10, 25), LONDON)
    end = start_of_day(date(2026, 11, 1), LONDON)
    assert end - start == timedelta(hours=168)          # the wrong answer, documented
    assert elapsed(start, end) == timedelta(hours=169)  # the right one
