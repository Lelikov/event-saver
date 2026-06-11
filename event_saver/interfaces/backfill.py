"""Protocol for the periodic user_id backfill background task."""

from typing import Protocol


class IUserIdBackfillRunner(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...
