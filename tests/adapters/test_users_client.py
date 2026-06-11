"""UsersHttpResolver: by-identity lookup, 404 handling, transport-error classification."""

import uuid

import httpx
import pytest

from event_saver.adapters.users_client import UsersHttpResolver
from event_saver.interfaces.user_resolver import UsersServiceUnavailableError


def make_resolver(handler) -> UsersHttpResolver:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="http://users.test")
    return UsersHttpResolver(http_client=client, api_token="token-123")  # noqa: S106


@pytest.mark.anyio
async def test_resolves_user_via_by_identity() -> None:
    user_id = uuid.uuid4()
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["params"] = dict(request.url.params)
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"id": str(user_id), "email": "a@x.com", "role": "client"})

    resolver = make_resolver(handler)
    resolved = await resolver.resolve(email="a+b@x.com", role="client")

    assert resolved == user_id
    assert captured["path"] == "/api/users/by-identity"
    assert captured["params"] == {"email": "a+b@x.com", "role": "client"}
    assert captured["auth"] == "Bearer token-123"


@pytest.mark.anyio
async def test_404_means_no_user() -> None:
    resolver = make_resolver(lambda _request: httpx.Response(404))
    assert await resolver.resolve(email="ghost@x.com", role="client") is None


@pytest.mark.anyio
async def test_5xx_raises_unavailable() -> None:
    resolver = make_resolver(lambda _request: httpx.Response(503))
    with pytest.raises(UsersServiceUnavailableError):
        await resolver.resolve(email="a@x.com", role="client")


@pytest.mark.anyio
async def test_transport_error_raises_unavailable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    resolver = make_resolver(handler)
    with pytest.raises(UsersServiceUnavailableError):
        await resolver.resolve(email="a@x.com", role="client")


@pytest.mark.anyio
async def test_malformed_id_raises_unavailable() -> None:
    resolver = make_resolver(lambda _request: httpx.Response(200, json={"id": "not-a-uuid"}))
    with pytest.raises(UsersServiceUnavailableError):
        await resolver.resolve(email="a@x.com", role="client")
