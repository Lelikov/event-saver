"""HTTP client for the users service."""

import uuid
from typing import Any

import structlog
from httpx import AsyncClient


logger = structlog.get_logger(__name__)


class UsersClient:
    def __init__(self, *, http_client: AsyncClient, api_token: str) -> None:
        self._client = http_client
        self._headers = {"Authorization": f"Bearer {api_token}"}

    async def get_user(self, user_id: uuid.UUID) -> dict[str, Any]:
        response = await self._client.get(
            f"/api/users/{user_id}",
            headers=self._headers,
        )
        response.raise_for_status()
        logger.debug("Fetched user from users service", user_id=str(user_id))
        return response.json()
