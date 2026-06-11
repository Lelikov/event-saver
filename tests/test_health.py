"""Tests for /health and /ready endpoints."""

import pytest

from event_saver import main


@pytest.fixture(autouse=True)
def _dsn_env(monkeypatch) -> None:
    monkeypatch.setenv("POSTGRES_DSN", "postgresql+asyncpg://u:p@localhost:5432/db")


class TestHealth:
    @pytest.mark.anyio
    async def test_health_returns_ok(self) -> None:
        assert await main.health() == {"status": "ok"}

    def test_routes_registered(self) -> None:
        paths = {route.path for route in main.app.routes}

        assert "/health" in paths
        assert "/ready" in paths


class TestReady:
    @pytest.mark.anyio
    async def test_ready_when_database_reachable(self, monkeypatch) -> None:
        async def _ok() -> bool:
            return True

        monkeypatch.setattr(main, "_check_database", _ok)
        response = await main.ready()

        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_unavailable_when_database_down(self, monkeypatch) -> None:
        async def _down() -> bool:
            return False

        monkeypatch.setattr(main, "_check_database", _down)
        response = await main.ready()

        assert response.status_code == 503
