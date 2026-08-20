"""Deciding whether a request is allowed to move money.

The PIN is compared here, on the server, against the configured value. It is
never returned to a client, never sent to one, and never embedded in the
bundle. Hiding a button in the frontend is presentation; this is the thing
that actually refuses a request, including one typed straight at the API by
somebody who never loaded the page.

The party is deliberately not taken from the request. A client says what it
wants done, never who it is: the identity is a property of the credential
that was proved, so it is derived here and nowhere else. Today one PIN means
one parent. When a second parent is authorised alongside the first, this is
the single place that changes.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import datetime

from app.config import get_settings
from app.models.base import utcnow

#: The party a correct PIN proves you to be. One today, by design.
PARENT = "parent"


class NotAuthorised(Exception):
    """The PIN was absent, empty or wrong. The caller learns nothing more."""


@dataclass(frozen=True)
class Authorisation:
    """Proof that a parent authorised this request, and when.

    Passed to whatever performs the write, so the record of who agreed what is
    taken from the credential rather than from anything the caller asserted.
    """

    party: str
    at: datetime


def verify_pin(offered: str | None) -> Authorisation:
    """Check a PIN and return who it proves the caller to be.

    Raises NotAuthorised for anything that is not the configured PIN. The
    comparison is constant-time: a PIN short enough for a child to watch being
    typed is short enough to guess a digit at a time from response timings.
    """
    if not offered:
        raise NotAuthorised("No PIN supplied.")

    expected = get_settings().parent_pin
    if not hmac.compare_digest(str(offered), expected):
        raise NotAuthorised("That PIN is not correct.")

    return Authorisation(party=PARENT, at=utcnow())
