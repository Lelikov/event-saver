"""Protocol for resolving user identities via the event-users service."""

from __future__ import annotations
import uuid
from typing import Protocol


class UsersServiceUnavailableError(Exception):
    """event-users could not answer (transport failure or 5xx) — back off and retry later."""


class IUserResolver(Protocol):
    async def resolve(self, *, email: str, role: str) -> uuid.UUID | None:
        """Return the event-users UUID for email+role, or None when no such user exists.

        Raises UsersServiceUnavailableError on transport-level failures.
        """
        ...
