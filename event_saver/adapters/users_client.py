"""HTTP client for the event-users service (identity resolution for the user_id backfill)."""

from __future__ import annotations
import uuid
from http import HTTPStatus

import httpx
import structlog

from event_saver.interfaces.user_resolver import IUserResolver, UsersServiceUnavailableError


logger = structlog.get_logger(__name__)


class UsersHttpResolver(IUserResolver):
    """Resolves email+role to a user UUID via GET /api/users/by-identity.

    Mirrors event-receiver's lookup (same endpoint, same Bearer token auth);
    unlike the receiver it never creates users — the backfill only reconciles
    rows the ingress path failed to resolve.
    """

    def __init__(self, *, http_client: httpx.AsyncClient, api_token: str) -> None:
        self._client = http_client
        self._headers = {"Authorization": f"Bearer {api_token}"}

    async def resolve(self, *, email: str, role: str) -> uuid.UUID | None:
        try:
            response = await self._client.get(
                "/api/users/by-identity",
                params={"email": email, "role": role},
                headers=self._headers,
            )
        except httpx.HTTPError as exc:
            raise UsersServiceUnavailableError(f"event-users transport failure: {exc!r}") from exc

        if response.status_code == HTTPStatus.NOT_FOUND:
            return None
        if response.status_code != HTTPStatus.OK:
            raise UsersServiceUnavailableError(f"event-users returned status {response.status_code}")

        raw_id = response.json().get("id")
        try:
            return uuid.UUID(raw_id)
        except (TypeError, ValueError) as exc:
            logger.warning("event-users returned a malformed user id", raw_id=raw_id, email=email, role=role)
            raise UsersServiceUnavailableError(f"event-users returned malformed id: {raw_id!r}") from exc
