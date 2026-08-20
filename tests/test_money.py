"""Money is integer pence. No float appears in this file, by design."""

from __future__ import annotations

import pytest

from app.services.money import MoneyError, format_pence, parse_pence


@pytest.mark.parametrize(
    ("pence", "shown"),
    [
        (0, "£0.00"),
        (1, "£0.01"),
        (9, "£0.09"),
        (10, "£0.10"),
        (100, "£1.00"),
        (450, "£4.50"),
        (123456, "£1234.56"),
        (-5, "-£0.05"),
        (-450, "-£4.50"),
    ],
)
def test_format_pence(pence, shown):
    assert format_pence(pence) == shown


def test_format_without_symbol():
    assert format_pence(450, symbol=False) == "4.50"


@pytest.mark.parametrize(
    ("typed", "pence"),
    [
        ("4.50", 450),
        ("£4.50", 450),
        ("  £ 4.50  ", 450),
        ("4", 400),
        ("4.5", 450),        # four pounds fifty, not four pounds and five pence
        (".5", 50),
        (".05", 5),
        ("0.07", 7),
        ("0", 0),
        ("1,234.56", 123456),
        ("450p", 450),
        ("7P", 7),
        ("-£4.50", -450),
        ("+4.50", 450),
    ],
)
def test_parse_pence(typed, pence):
    assert parse_pence(typed) == pence


@pytest.mark.parametrize(
    "typed",
    ["", "   ", "abc", "£", "4.5.6", "--4", "1.234", "4.50.", "p", "4 50", "£4,5"],
)
def test_parse_rejects_nonsense(typed):
    with pytest.raises(MoneyError):
        parse_pence(typed)


def test_parse_refuses_to_round_a_third_decimal():
    # An amount that cannot be paid is a typing mistake, not a value to guess.
    with pytest.raises(MoneyError):
        parse_pence("1.005")


@pytest.mark.parametrize(
    "pence",
    [0, 1, 7, 9, 10, 99, 100, 101, 450, 999, 1000, 12345, 99999, -1, -450],
)
def test_round_trip_pence_to_pounds_and_back(pence):
    assert parse_pence(format_pence(pence)) == pence


def test_round_trip_over_every_penny_of_two_pounds():
    # Exhaustive across the carry boundaries, where a float would drift.
    for pence in range(0, 201):
        assert parse_pence(format_pence(pence)) == pence


def test_a_float_is_not_an_amount():
    with pytest.raises(MoneyError):
        format_pence(4.5)  # type: ignore[arg-type]
    with pytest.raises(MoneyError):
        parse_pence(4.5)  # type: ignore[arg-type]


def test_a_bool_is_not_an_amount():
    with pytest.raises(MoneyError):
        format_pence(True)  # type: ignore[arg-type]


def test_amounts_add_as_integers():
    week = [parse_pence("2.10"), parse_pence("0.05"), parse_pence("1.35")]
    assert sum(week) == 350
    assert format_pence(sum(week)) == "£3.50"


def test_the_penny_that_floats_lose():
    # 0.1 + 0.2 != 0.3 in binary floating point. In pence it is exact.
    assert parse_pence("0.10") + parse_pence("0.20") == parse_pence("0.30")
