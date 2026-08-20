"""Money.

Every monetary value in CoinQuest is an integer number of pence. Floating
point never touches currency: not in the database, not in the API, not in a
calculation, not in a test. A ledger that drifts by a penny is a ledger nobody
trusts, and binary floats cannot represent 0.10 exactly.

Pounds exist only at the two edges of the system — text shown to a person, and
text typed by one — which is what this module is for. Between those edges,
amounts are `int`.
"""

from __future__ import annotations

import re

PENCE_PER_POUND = 100


class MoneyError(ValueError):
    """Raised when text offered as an amount is not one."""


def format_pence(pence: int, *, symbol: bool = True) -> str:
    """Render pence for display: 450 -> '£4.50', -5 -> '-£0.05'.

    The sign leads the symbol, as it is written in English.
    """
    if not isinstance(pence, int) or isinstance(pence, bool):
        raise MoneyError(f"Amounts are integer pence, got {pence!r}.")

    sign = "-" if pence < 0 else ""
    whole, part = divmod(abs(pence), PENCE_PER_POUND)
    return f"{sign}{'£' if symbol else ''}{whole}.{part:02d}"


# An optional sign, an optional £, then either pounds with optional pence, or
# a bare '.50'. Thousands separators are tolerated because people type them.
_POUNDS = re.compile(
    r"""
    ^
    (?P<sign>[-+])?
    \s*
    £?
    \s*
    (?:
        (?P<whole>\d{1,3}(?:,\d{3})*|\d+)
        (?:\.(?P<part>\d{1,2}))?
      |
        \.(?P<part_only>\d{1,2})
    )
    $
    """,
    re.VERBOSE,
)

# The same amount written in pence: '450p'.
_PENCE = re.compile(r"^(?P<sign>[-+])?\s*(?P<pence>\d+)\s*p$", re.IGNORECASE)


def parse_pence(text: str) -> int:
    """Read an amount typed by a person and return integer pence.

    Accepts '4.50', '£4.50', '4', '.5', '1,234.56' and '450p'. Rejects
    anything with more than two decimal places rather than rounding it: an
    amount that cannot be paid is a typing mistake, not a value to guess at.
    """
    if not isinstance(text, str):
        raise MoneyError(f"Expected an amount as text, got {text!r}.")

    cleaned = text.strip()
    if not cleaned:
        raise MoneyError("No amount given.")

    match = _PENCE.match(cleaned)
    if match:
        pence = int(match["pence"])
        return -pence if match["sign"] == "-" else pence

    match = _POUNDS.match(cleaned)
    if not match:
        raise MoneyError(f"{text!r} is not an amount.")

    whole = int((match["whole"] or "0").replace(",", ""))
    # '4.5' is four pounds fifty, not four pounds and five pence.
    part_text = match["part"] or match["part_only"] or "0"
    part = int(part_text.ljust(2, "0"))

    pence = whole * PENCE_PER_POUND + part
    return -pence if match["sign"] == "-" else pence
