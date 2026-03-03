from typing import Protocol


class IEventConsumerRunner(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...
