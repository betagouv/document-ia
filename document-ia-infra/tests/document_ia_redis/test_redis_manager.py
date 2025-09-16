from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from document_ia_redis.redis_manager import RedisManager


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
                "document_ia_redis.redis_manager.ConnectionPool.from_url",
                return_value=mock_pool,
            ) as pool_mock,
            patch(
                "document_ia_redis.redis_manager.Redis", return_value=mock_redis
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
                "document_ia_redis.redis_manager.ConnectionPool.from_url",
                return_value=mock_pool,
            ),
            patch("document_ia_redis.redis_manager.Redis", return_value=mock_redis),
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
                "document_ia_redis.redis_manager.ConnectionPool.from_url",
                return_value=mock_pool,
            ),
            patch("document_ia_redis.redis_manager.Redis", return_value=mock_redis),
            patch("asyncio.sleep", return_value=None),
        ):
            conn = await manager.get_connection()

        assert conn is None
        # Atteint le max
        assert manager.connection_attempts == manager.max_retries

    @pytest.mark.asyncio
    async def test_close(self):
        manager = RedisManager()
        mock_redis = MagicMock()
        mock_redis.close = AsyncMock()
        manager.redis = mock_redis

        await manager.close()
        mock_redis.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_sans_connexion(self):
        manager = RedisManager()
        # Ne doit pas lever
        await manager.close()
        assert manager.redis is None
