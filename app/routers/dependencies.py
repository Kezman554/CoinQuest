"""Shared FastAPI dependencies: the database session, and authorisation."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request, status
from pydantic import BaseModel, SecretStr
from sqlalchemy.orm import Session

from app.db import get_session_factory
from app.services.authorisation import Authorisation, NotAuthorised, verify_pin
from app.services.lockout import LockedOut, get_limiter


def get_session() -> Iterator[Session]:
    """A session per request.

    Nothing is committed here. A request that changes anything commits once,
    itself, when it knows the whole change is good — which is what makes a
    batch all-or-nothing.
    """
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


class AuthorisedRequest(BaseModel):
    """Base for any body that has to prove it may move money.

    SecretStr so the PIN cannot be echoed back by accident: it does not appear
    in a repr, in a log line, or in a validation error naming the offending
    value. It is read once, compared, and dropped.
    """

    pin: SecretStr


def source_of(request: Request) -> str:
    """Where the request came from, as the socket reports it.

    Taken from the transport and never from the request itself. A caller can
    put anything in a header, so a limit keyed on what they say about
    themselves limits nobody. See app.services.lockout for what this means
    behind a proxy.
    """
    client = request.client
    return client.host if client and client.host else "unknown"


def authorise(request: Request, body: AuthorisedRequest) -> Authorisation:
    """Verify the PIN carried by a request body, or refuse the request.

    Checked against the attempt limiter first: a source still cooling off is
    refused whatever it sends, because a window a correct guess could open
    early would not be a limit at all.

    The two refusals say different amounts on purpose. A wrong PIN is told
    nothing — not whether one was supplied, how long it should be, or how
    close it was. A lockout is told plainly how long remains, because the
    likeliest person reading it is a parent who mistyped, and an attacker
    learns nothing from it that a clock would not tell them.
    """
    limiter = get_limiter()
    source = source_of(request)

    try:
        limiter.check(source)
    except LockedOut as locked:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(locked),
            headers={"Retry-After": str(locked.seconds_remaining)},
        ) from None

    try:
        authorisation = verify_pin(body.pin.get_secret_value())
    except NotAuthorised:
        limiter.record_failure(source)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authorised.",
        ) from None

    limiter.record_success(source)
    return authorisation


SessionDep = Depends(get_session)
