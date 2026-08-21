"""The scheme's own settings — currently one figure, the weekly basic pay.

Reading needs no PIN, same as every other GET; writing does, same as every
other change that reshapes what the scheme pays.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

PIN = "0000"
WRONG = "9999"


@pytest.fixture()
def api(session):
    from app.main import app
    from app.routers.dependencies import get_session

    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_the_seeded_default_is_two_pounds(api):
    response = api.get("/api/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["weekly_basic_pay_pence"] == 200
    assert body["weekly_basic_pay"] == "£2.00"


def test_reading_needs_no_pin(api):
    # No pin field at all in the request, not even a wrong one.
    assert api.get("/api/settings").status_code == 200


def test_updating_needs_the_pin(api):
    response = api.post("/api/settings", json={"pin": WRONG, "weekly_basic_pay_pence": 300})
    assert response.status_code == 401
    assert api.get("/api/settings").json()["weekly_basic_pay_pence"] == 200


def test_updating_needs_a_pin_at_all(api):
    response = api.post("/api/settings", json={"weekly_basic_pay_pence": 300})
    assert response.status_code == 422


def test_updating_changes_the_figure(api):
    response = api.post("/api/settings", json={"pin": PIN, "weekly_basic_pay_pence": 300})
    assert response.status_code == 200
    body = response.json()
    assert body["weekly_basic_pay_pence"] == 300
    assert body["weekly_basic_pay"] == "£3.00"

    # And it stuck.
    assert api.get("/api/settings").json()["weekly_basic_pay_pence"] == 300


def test_a_negative_figure_is_refused(api):
    response = api.post("/api/settings", json={"pin": PIN, "weekly_basic_pay_pence": -50})
    assert response.status_code == 422
    assert api.get("/api/settings").json()["weekly_basic_pay_pence"] == 200


def test_zero_is_allowed(api):
    """No basic chore pay at all is a legitimate, if unusual, setting."""
    response = api.post("/api/settings", json={"pin": PIN, "weekly_basic_pay_pence": 0})
    assert response.status_code == 200
    assert response.json()["weekly_basic_pay_pence"] == 0
