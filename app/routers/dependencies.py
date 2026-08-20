"""Shared FastAPI dependencies: the database session, and authorisation."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, status
from pydantic import BaseModel, SecretStr
from sqlalchemy.orm import Session

from app.db import get_session_factory
from app.services.authorisation import Authorisation, NotAuthorised, verify_pin


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


def authorise(body: AuthorisedRequest) -> Authorisation:
    """Verify the PIN carried by a request body, or refuse the request.

    The refusal is deliberately uninformative. It does not say whether a PIN
    was supplied, how long it should be, or how close this one was.
    """
    try:
        return verify_pin(body.pin.get_secret_value())
    except NotAuthorised:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authorised.",
        ) from None


SessionDep = Depends(get_session)
