"""Interface for users service client."""

import uuid
from typing import Any, Protocol


class IUsersClient(Protocol):
    async def get_user(self, user_id: uuid.UUID) -> dict[str, Any]: ...
