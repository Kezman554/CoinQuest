"""Attempt limiting on the PIN.

The unit tests drive a fake clock, so a cooling-off can be waited out without
the suite waiting with it. The endpoint tests go through the real app.
"""

from __future__ import annotations

import logging
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.models import Week
from app.services.lockout import AttemptLimiter, LockedOut, describe_wait

PIN = "0000"
WRONG = "9999"
SUNDAY = date(2026, 8, 16)
SATURDAY = date(2026, 8, 22)


class FakeClock:
    """A clock that only moves when the test says so."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture()
def limiter(clock) -> AttemptLimiter:
    return AttemptLimiter(
        limit=3, cool_off_start_seconds=60, cool_off_max_seconds=240, clock=clock
    )


# --- 1. Consecutive failures, counted, and then refused ---------------------


def test_failures_below_the_limit_do_not_lock_anything(limiter):
    for _ in range(2):
        limiter.record_failure("10.0.0.5")
    limiter.check("10.0.0.5")  # still answering


def test_the_limit_stops_the_source_answering(limiter):
    for _ in range(3):
        limiter.record_failure("10.0.0.5")
    with pytest.raises(LockedOut):
        limiter.check("10.0.0.5")


def test_a_correct_pin_clears_the_count(limiter):
    limiter.record_failure("10.0.0.5")
    limiter.record_failure("10.0.0.5")
    limiter.record_success("10.0.0.5")

    # The limit is on consecutive misses, so the count starts again.
    limiter.record_failure("10.0.0.5")
    limiter.record_failure("10.0.0.5")
    limiter.check("10.0.0.5")


def test_a_locked_source_is_refused_even_with_the_right_pin(api, session):
    # Checked before the PIN is looked at. A window a correct guess could open
    # early would not be a limit at all.
    for _ in range(5):
        api.post("/api/claims", json={"instance_id": 1})
    lock_out(api)

    response = api.post(
        "/api/savings/opening-balance", json={"pin": PIN, "amount_pence": 100}
    )
    assert response.status_code == 429


# --- 2. It clears itself, with time ----------------------------------------


def test_the_cooling_off_expires_on_its_own(limiter, clock):
    for _ in range(3):
        limiter.record_failure("10.0.0.5")
    with pytest.raises(LockedOut):
        limiter.check("10.0.0.5")

    clock.advance(61)
    limiter.check("10.0.0.5")  # no administrator required, and none exists


def test_the_count_starts_again_after_a_cooling_off(limiter, clock):
    for _ in range(3):
        limiter.record_failure("10.0.0.5")
    clock.advance(61)
    limiter.check("10.0.0.5")

    # Two more failures do not immediately re-lock: the slate was wiped.
    limiter.record_failure("10.0.0.5")
    limiter.record_failure("10.0.0.5")
    limiter.check("10.0.0.5")


def test_time_still_has_to_pass(limiter, clock):
    for _ in range(3):
        limiter.record_failure("10.0.0.5")
    clock.advance(59)
    with pytest.raises(LockedOut):
        limiter.check("10.0.0.5")


# --- The cooling-off escalates ----------------------------------------------


def test_the_first_cooling_off_is_the_short_one(limiter):
    # The kitchen screen is shared, so the common case is a mistype or a bored
    # child, and neither should cost an evening.
    assert limiter.cool_off_for(1) == 60


def test_each_consecutive_lockout_doubles(limiter):
    assert [limiter.cool_off_for(n) for n in range(1, 5)] == [60, 120, 240, 240]


def test_the_doubling_stops_at_the_cap(limiter):
    # An hours-long lockout punishes the household, not the guesser.
    assert limiter.cool_off_for(10) == 240
    assert limiter.cool_off_for(100) == 240


def test_the_default_escalation_is_thirty_seconds_to_a_quarter_hour():
    from app.services.lockout import AttemptLimiter as Limiter

    real = Limiter(limit=5, cool_off_start_seconds=30, cool_off_max_seconds=900)
    assert [real.cool_off_for(n) for n in range(1, 8)] == [
        30, 60, 120, 240, 480, 900, 900
    ]


def lock_out_once(limiter, source="10.0.0.5"):
    for _ in range(3):
        limiter.record_failure(source)


def test_a_second_lockout_lasts_twice_as_long(limiter, clock):
    lock_out_once(limiter)
    assert limiter.seconds_remaining("10.0.0.5") == 61

    clock.advance(61)
    limiter.check("10.0.0.5")          # served, and counting starts again
    lock_out_once(limiter)
    assert limiter.seconds_remaining("10.0.0.5") == 121   # not 61


def test_waiting_a_cooling_off_out_does_not_reset_the_escalation(limiter, clock):
    # Otherwise somebody working through the keyspace would simply wait each
    # one out and never face anything longer than the first.
    for expected in (61, 121, 241, 241):
        lock_out_once(limiter)
        assert limiter.seconds_remaining("10.0.0.5") == expected
        clock.advance(expected)
        limiter.check("10.0.0.5")


def test_a_correct_pin_puts_the_escalation_back_to_the_start(limiter, clock):
    lock_out_once(limiter)
    clock.advance(61)
    limiter.check("10.0.0.5")
    lock_out_once(limiter)
    assert limiter.seconds_remaining("10.0.0.5") == 121

    clock.advance(121)
    limiter.check("10.0.0.5")
    limiter.record_success("10.0.0.5")   # they got in

    lock_out_once(limiter)
    assert limiter.seconds_remaining("10.0.0.5") == 61   # back to the short one


def test_the_escalation_is_per_source(limiter, clock):
    lock_out_once(limiter, "10.0.0.5")
    clock.advance(61)
    limiter.check("10.0.0.5")
    lock_out_once(limiter, "10.0.0.5")
    assert limiter.seconds_remaining("10.0.0.5") == 121

    lock_out_once(limiter, "10.0.0.9")
    assert limiter.seconds_remaining("10.0.0.9") == 61


def test_guessing_the_whole_keyspace_takes_far_longer_than_a_flat_wait(limiter):
    # The reason for escalating at all, in numbers. Five guesses per lockout,
    # ten thousand PINs to try: a flat five minutes lets it through in about a
    # week, while doubling to a fifteen-minute ceiling does not.
    from app.services.lockout import AttemptLimiter as Limiter

    real = Limiter(limit=5, cool_off_start_seconds=30, cool_off_max_seconds=900)
    lockouts_needed = 10_000 // 5

    flat_days = (lockouts_needed * 300) / 86_400
    escalating_days = sum(real.cool_off_for(n) for n in range(1, lockouts_needed + 1)) / 86_400

    assert flat_days < 7           # inside a week
    assert escalating_days > 20    # and now it is not


# --- 3. Keyed on the source address, and on nothing it says about itself ----


def test_one_source_locking_itself_out_does_not_affect_another(limiter):
    for _ in range(3):
        limiter.record_failure("10.0.0.5")
    with pytest.raises(LockedOut):
        limiter.check("10.0.0.5")

    # The parent's phone is untouched by whatever the laptop is doing. This is
    # the whole reason for counting per source rather than globally.
    limiter.check("10.0.0.9")


def test_the_source_comes_from_the_socket_not_from_a_header():
    from unittest.mock import Mock

    from app.routers.dependencies import source_of

    request = Mock()
    request.client.host = "10.0.0.5"
    request.headers = {"X-Forwarded-For": "1.2.3.4", "Host": "somewhere-else"}

    # Anything the caller says about itself is ignored: a limiter keyed on a
    # claim limits nobody, because the claim can be changed at will.
    assert source_of(request) == "10.0.0.5"


def test_a_request_with_no_client_still_gets_counted():
    from unittest.mock import Mock

    from app.routers.dependencies import source_of

    request = Mock()
    request.client = None
    assert source_of(request) == "unknown"


# --- 4. The refusal says how long is left -----------------------------------


@pytest.mark.parametrize(
    ("seconds", "wording"),
    [
        (1, "1 second."),       # not "1 seconds"
        (30, "30 seconds"),
        (60, "60 seconds"),
        (61, "about 2 minutes"),
        (300, "about 5 minutes"),
        (3600, "about 60 minutes"),
    ],
)
def test_the_wait_is_stated_in_words(seconds, wording):
    assert wording in describe_wait(seconds)


def test_the_wait_shrinks_as_it_is_served(limiter, clock):
    for _ in range(3):
        limiter.record_failure("10.0.0.5")
    assert limiter.seconds_remaining("10.0.0.5") == 61

    clock.advance(30)
    assert limiter.seconds_remaining("10.0.0.5") == 31


# --- 5. Failures are logged -------------------------------------------------


def test_every_failure_is_logged(limiter, caplog):
    # This test found a real bug: alembic's fileConfig disables every existing
    # logger by default, so running a migration in-process silenced this one.
    # env.py now passes disable_existing_loggers=False.
    with caplog.at_level(logging.WARNING, logger="coinquest.authorisation"):
        for _ in range(3):
            limiter.record_failure("10.0.0.5")

    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 3
    assert "10.0.0.5" in messages[0]
    # The last one records the lockout itself, so a burst is visible after the
    # fact. Nobody is watching in real time; the log is how anyone finds out.
    assert "lockout" in messages[-1].lower()


def test_the_log_never_contains_the_pin(api, session, caplog):
    with caplog.at_level(logging.WARNING):
        api.post(
            "/api/savings/opening-balance",
            json={"pin": "1234", "amount_pence": 100},
        )
    assert "1234" not in caplog.text


# --- Through the running app ------------------------------------------------


@pytest.fixture()
def api(session, monkeypatch):
    """The app, with a limit small enough to reach and short enough to wait."""
    monkeypatch.setenv("PIN_ATTEMPT_LIMIT", "3")
    monkeypatch.setenv("PIN_COOL_OFF_START_SECONDS", "1")
    monkeypatch.setenv("PIN_COOL_OFF_MAX_SECONDS", "4")

    from app.config import get_settings
    from app.main import app
    from app.routers.dependencies import get_session
    from app.services.lockout import reset_limiter

    get_settings.cache_clear()
    reset_limiter()

    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    get_settings.cache_clear()
    reset_limiter()


def lock_out(api) -> dict:
    """Guess wrong until the service stops answering."""
    for _ in range(3):
        response = api.post(
            "/api/savings/opening-balance", json={"pin": WRONG, "amount_pence": 100}
        )
        assert response.status_code == 401
    return response.json()


def test_the_endpoint_refuses_after_enough_wrong_pins(api, session):
    lock_out(api)

    refused = api.post(
        "/api/savings/opening-balance", json={"pin": WRONG, "amount_pence": 100}
    )
    assert refused.status_code == 429
    assert "Try again in" in refused.json()["detail"]
    assert refused.headers["Retry-After"] == "1"  # the first cool-off is a second


def test_a_wrong_pin_still_gives_nothing_away(api, session):
    response = api.post(
        "/api/savings/opening-balance", json={"pin": WRONG, "amount_pence": 100}
    )
    # Not how many attempts are left, not how long the PIN is, not how close.
    assert response.json()["detail"] == "Not authorised."


def test_the_lockout_clears_itself_and_the_pin_works_again(api, session):
    import time

    lock_out(api)
    assert (
        api.post(
            "/api/savings/opening-balance", json={"pin": PIN, "amount_pence": 100}
        ).status_code
        == 429
    )

    time.sleep(2.1)  # the cooling-off, set to one second for this test

    accepted = api.post(
        "/api/savings/opening-balance", json={"pin": PIN, "amount_pence": 100}
    )
    assert accepted.status_code == 201  # and nothing was restarted


def test_a_lockout_blocks_every_authorised_route_not_just_the_one(api, session):
    week = Week(start_date=SUNDAY, end_date=SATURDAY)
    session.add(week)
    session.commit()
    lock_out(api)

    for path, body in (
        ("/api/claims/review", {"pin": PIN, "decisions": [{"instance_id": 1, "decision": "confirm"}]}),
        (f"/api/weeks/{week.id}/void", {"pin": PIN, "reason": "Away"}),
        ("/api/rewards", {"pin": PIN, "amount_pence": 100, "reason": "Because"}),
        ("/api/rewards/presets/eagle_award", {"pin": PIN}),
    ):
        assert api.post(path, json=body).status_code == 429, path


def test_reading_is_never_locked_out(api, session):
    # The child checking where he stands is not an authorisation attempt and
    # must not be caught by somebody else's guessing.
    week = Week(start_date=SUNDAY, end_date=SATURDAY)
    session.add(week)
    session.commit()
    lock_out(api)

    assert api.get("/api/weeks").status_code == 200
    assert api.get(f"/api/weeks/{week.id}/proposal").status_code == 200
    assert api.get("/api/rewards/presets").status_code == 200
    assert api.get("/health").status_code == 200


def test_a_correct_pin_before_the_limit_resets_the_count(api, session):
    for _ in range(2):
        api.post("/api/savings/opening-balance", json={"pin": WRONG, "amount_pence": 100})

    accepted = api.post(
        "/api/savings/opening-balance", json={"pin": PIN, "amount_pence": 100}
    )
    assert accepted.status_code == 201

    # Two more wrong ones would have locked it out had the count carried over.
    for _ in range(2):
        response = api.post("/api/rewards", json={"pin": WRONG, "amount_pence": 1, "reason": "x"})
        assert response.status_code == 401


def test_the_endpoint_escalates_between_lockouts(api, session):
    import time

    lock_out(api)
    first = api.post(
        "/api/savings/opening-balance", json={"pin": WRONG, "amount_pence": 100}
    )
    assert first.headers["Retry-After"] == "1"

    time.sleep(1.2)
    lock_out(api)
    second = api.post(
        "/api/savings/opening-balance", json={"pin": WRONG, "amount_pence": 100}
    )
    assert second.headers["Retry-After"] == "2"   # doubled, not repeated
