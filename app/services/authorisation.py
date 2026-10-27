"""Deciding whether a request is allowed to move money, and who allowed it.

The PIN is compared here, on the server, against the configured values. It is
never returned to a client, never sent to one, and never embedded in the
bundle. Hiding a button in the frontend is presentation; this is the thing
that actually refuses a request, including one typed straight at the API by
somebody who never loaded the page.

The party is deliberately not taken from the request. A client says what it
wants done, never who it is: the identity is a property of the credential
that was proved, so it is derived here and nowhere else. Each configured
parent has their own PIN (app.config, PARENT_n_NAME / PARENT_n_PIN), and a
correct PIN proves which parent is acting: the party recorded against what
they authorise is that parent's name. Rows written before there was more than
one parent carry PARENT, "parent", and keep it — the tables are append-only.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import datetime

from app.config import get_settings
from app.models.base import utcnow

#: The party every authorisation recorded before parents had names of their
#: own. Never written now; kept so the old rows can be read for what they are.
PARENT = "parent"


class NotAuthorised(Exception):
    """The PIN was absent, empty or wrong. The caller learns nothing more."""


@dataclass(frozen=True)
class Authorisation:
    """Proof that a parent authorised this request, which one, and when.

    Passed to whatever performs the write, so the record of who agreed what is
    taken from the credential rather than from anything the caller asserted.
    `bank_holder` is whether that parent is the one configured to pay the
    savings match into the bank (app.config, BANK_HOLDER) — false unless a
    PIN proved it.
    """

    party: str
    at: datetime
    bank_holder: bool = False


def verify_pin(offered: str | None) -> Authorisation:
    """Check a PIN and return which parent it proves the caller to be.

    Raises NotAuthorised for anything that is not a configured PIN. Every
    comparison is constant-time, and every configured PIN is compared, with
    no early exit: a PIN short enough for a child to watch being typed is
    short enough to guess a digit at a time from response timings, or to
    learn from them which parent's PIN a guess came close to.
    """
    if not offered:
        raise NotAuthorised("No PIN supplied.")

    settings = get_settings()
    offered_bytes = str(offered).encode()
    proved = None
    for parent in settings.parents:
        if hmac.compare_digest(offered_bytes, parent.pin.encode()):
            proved = parent
    if proved is None:
        raise NotAuthorised("That PIN is not correct.")

    return Authorisation(
        party=proved.name,
        at=utcnow(),
        bank_holder=proved.number == settings.bank_holder.number,
    )
