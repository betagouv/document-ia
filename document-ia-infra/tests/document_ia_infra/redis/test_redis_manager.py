from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import AuthenticationError

from document_ia_infra.redis.redis_manager import RedisManager


class TestRedisManager:
    @pytest.mark.asyncio
    async def test_initialisation(self):
        manager = RedisManager()
        assert manager.redis is None
        assert manager.connection_attempts == 0
        assert manager.max_retries == 3

    @pytest.mark.asyncio
    async def test_connexion_succes(self):
        manager = RedisManager()

        mock_pool = MagicMock()
        mock_redis = MagicMock()
        mock_redis.ping = AsyncMock(return_value=True)

        with (
            patch(
                "document_ia_infra.redis.redis_manager.ConnectionPool.from_url",
                return_value=mock_pool,
            ) as pool_mock,
            patch(
                "document_ia_infra.redis.redis_manager.Redis", return_value=mock_redis
            ) as redis_cls,
        ):
            conn = await manager.get_connection()

        assert conn is mock_redis
        assert manager.redis is mock_redis
        assert manager.connection_attempts == 0
        pool_mock.assert_called_once()
        redis_cls.assert_called_once_with(connection_pool=mock_pool)
        mock_redis.ping.assert_awaited()

    @pytest.mark.asyncio
    async def test_connexion_avec_retries_puis_succes(self):
        manager = RedisManager()
        manager.max_retries = 5

        mock_pool = MagicMock()
        mock_redis = MagicMock()
        # Simule 2 échecs puis succès
        mock_redis.ping = AsyncMock(
            side_effect=[ConnectionError("down"), ConnectionError("down"), True]
        )

        sleep_calls = []

        async def fake_sleep(d):
            sleep_calls.append(d)
            # ne rien attendre réellement
            return

        with (
            patch(
                "document_ia_infra.redis.redis_manager.ConnectionPool.from_url",
                return_value=mock_pool,
            ),
            patch(
                "document_ia_infra.redis.redis_manager.Redis", return_value=mock_redis
            ),
            patch("asyncio.sleep", side_effect=fake_sleep),
        ):
            conn = await manager.get_connection()

        assert conn is mock_redis
        # Après succès on remet à 0
        assert manager.connection_attempts == 0
        # On a au moins deux sleeps (pour les deux échecs)
        assert len(sleep_calls) == 2
        assert all(d > 0 for d in sleep_calls)

    @pytest.mark.asyncio
    async def test_connexion_echec_max_retries(self):
        manager = RedisManager()
        manager.max_retries = 3

        mock_pool = MagicMock()
        mock_redis = MagicMock()
        mock_redis.ping = AsyncMock(side_effect=ConnectionError("still down"))

        with (
            patch(
                "document_ia_infra.redis.redis_manager.ConnectionPool.from_url",
                return_value=mock_pool,
            ),
            patch(
                "document_ia_infra.redis.redis_manager.Redis", return_value=mock_redis
            ),
            patch("asyncio.sleep", return_value=None),
        ):
            conn = await manager.get_connection()

        assert conn is None
        assert manager.redis is None
        # Atteint le max
        assert manager.connection_attempts == manager.max_retries

    @pytest.mark.asyncio
    async def test_reconnexion_apres_echec_max_retries(self):
        manager = RedisManager()
        manager.max_retries = 3

        mock_pool = MagicMock()
        failing_redis = MagicMock()
        failing_redis.ping = AsyncMock(side_effect=ConnectionError("still down"))
        failing_redis.close = AsyncMock()

        healthy_redis = MagicMock()
        healthy_redis.ping = AsyncMock(return_value=True)

        with (
            patch(
                "document_ia_infra.redis.redis_manager.ConnectionPool.from_url",
                return_value=mock_pool,
            ),
            patch(
                "document_ia_infra.redis.redis_manager.Redis",
                side_effect=[failing_redis, healthy_redis],
            ),
            patch("asyncio.sleep", return_value=None),
        ):
            first = await manager.get_connection()
            assert first is None
            assert manager.redis is None
            failing_redis.close.assert_awaited_once()

            second = await manager.get_connection()
            assert second is healthy_redis
            assert manager.redis is healthy_redis
            assert manager.connection_attempts == 0

    @pytest.mark.asyncio
    async def test_close(self):
        manager = RedisManager()
        mock_redis = MagicMock()
        mock_redis.aclose = AsyncMock()
        manager.redis = mock_redis
        manager.connection_attempts = 2

        await manager.close()
        await manager.close()  # Idempotent owner shutdown.
        mock_redis.aclose.assert_awaited_once_with(close_connection_pool=True)
        assert manager.redis is None
        assert manager.connection_attempts == 0

    @pytest.mark.asyncio
    async def test_failed_close_keeps_resource_for_owner_retry(self):
        manager = RedisManager()
        client = MagicMock()
        client.aclose = AsyncMock(side_effect=[ConnectionError("close failed"), None])
        manager.redis = client
        with pytest.raises(ConnectionError, match="close failed"):
            await manager.close()
        assert manager.redis is client
        await manager.close()
        assert manager.redis is None
        assert client.aclose.await_count == 2

    @pytest.mark.asyncio
    async def test_close_sans_connexion(self):
        manager = RedisManager()
        # Ne doit pas lever
        await manager.close()
        assert manager.redis is None

    @pytest.mark.asyncio
    async def test_auth_fallback_keeps_the_configured_endpoint(self):
        """Reconnecting without a password must not move to another server.

        When `REDIS_URL` supplies the endpoint, the fallback used to rebuild the
        URL from `REDIS_HOST`/`REDIS_PORT`/`REDIS_DB`, silently switching to
        localhost database 0.
        """
        manager = RedisManager()
        rejected = MagicMock()
        rejected.ping = AsyncMock(
            side_effect=AuthenticationError("without any password configured")
        )
        rejected.aclose = AsyncMock()
        accepted = MagicMock()
        accepted.ping = AsyncMock(return_value=True)

        with (
            patch(
                "document_ia_infra.redis.redis_manager.redis_settings",
                new=MagicMock(
                    get_redis_url=lambda: "redis://:secret@redis.internal:6390/4",
                    get_redis_url_without_credentials=lambda: (
                        "redis://redis.internal:6390/4"
                    ),
                ),
            ),
            patch(
                "document_ia_infra.redis.redis_manager.ConnectionPool.from_url"
            ) as pool_mock,
            patch(
                "document_ia_infra.redis.redis_manager.Redis",
                side_effect=[rejected, accepted],
            ),
        ):
            conn = await manager.get_connection()

        assert conn is accepted
        urls = [call.args[0] for call in pool_mock.call_args_list]
        assert urls == [
            "redis://:secret@redis.internal:6390/4",
            "redis://redis.internal:6390/4",
        ]
        # The remote endpoint, port and database survive the fallback.
        assert not any("localhost" in url for url in urls)

    def test_url_without_credentials_preserves_endpoint(self):
        """Credential stripping keeps host, port, database, scheme and options."""
        from document_ia_infra.redis.redis_settings import RedisSettings

        settings = RedisSettings(
            REDIS_URL="rediss://user:pw@redis.internal:6390/4?ssl_cert_reqs=none",
            REDIS_PASSWORD="pw",
        )

        assert (
            settings.get_redis_url_without_credentials()
            == "rediss://redis.internal:6390/4?ssl_cert_reqs=none"
        )

    def test_url_without_credentials_from_individual_settings(self):
        from document_ia_infra.redis.redis_settings import RedisSettings

        settings = RedisSettings(
            REDIS_HOST="10.1.2.3",
            REDIS_PORT=6380,
            REDIS_DB=2,
            REDIS_PASSWORD="p@ss word",
        )

        stripped = settings.get_redis_url_without_credentials()
        assert stripped == "redis://10.1.2.3:6380/2"
        # The password materialises only in the credentialed form.
        assert "p%40ss%20word" in settings.get_redis_url()

    @pytest.mark.asyncio
    async def test_recovers_on_next_call_after_exhausting_retries(self):
        manager = RedisManager()
        manager.max_retries = 1
        client = MagicMock()
        client.ping = AsyncMock(side_effect=[ConnectionError("down"), True])
        client.aclose = AsyncMock()
        client.close = AsyncMock()
        manager.redis = client
        with (
            patch("document_ia_infra.redis.redis_manager.ConnectionPool.from_url"),
            patch("document_ia_infra.redis.redis_manager.Redis", return_value=client),
            patch("asyncio.sleep", new=AsyncMock()),
        ):
            assert await manager.get_connection() is None
            assert await manager.get_connection() is client
        assert client.ping.await_count == 2
