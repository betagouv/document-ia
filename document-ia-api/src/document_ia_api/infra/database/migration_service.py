import asyncio
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

from document_ia_infra.data.data_settings import (
    analytics_database_settings,
    database_settings,
)
from document_ia_infra.data.database import (
    database_manager,
    get_analytics_database_manager,
)

logger = logging.getLogger(__name__)


class MigrationService:
    def __init__(self):
        project_root = Path(__file__).resolve().parents[4]
        self.alembic_ini_path = project_root / "alembic.ini"
        self.alembic_script_location = project_root / "alembic"

    async def _get_db_revision(self, engine: AsyncEngine) -> str | None:
        """Retourne la révision Alembic en DB (ou None si table absente)."""
        async with engine.connect() as conn:
            try:
                res = await conn.exec_driver_sql(
                    "SELECT version_num FROM alembic_version"
                )
                return res.scalar_one_or_none()
            except ProgrammingError:
                # table alembic_version absente
                return None

    def _revisions_between(
        self, cfg: Config, lower: str | None, upper: str | None
    ) -> list[str]:
        """
        Retourne la liste des révisions à appliquer pour aller de `lower` -> `upper`.
        - `lower` peut être None (équivaut à <base>)
        - L’ordre retourné est du plus ancien vers le plus récent.
        """
        script = ScriptDirectory.from_config(cfg)

        # Alembic itère à l’envers; on inverse à la fin pour un ordre chronologique
        lower_ref = lower or "base"
        upper_ref = upper or "head"

        revs = list(script.iterate_revisions(upper=upper_ref, lower=lower_ref))
        revs.reverse()  # ordre base -> head

        out: list[str] = []
        for r in revs:
            msg = (r.doc or "").strip()
            label = f"{r.revision}" if not msg else f"{r.revision} - {msg}"
            out.append(label)
        return out

    async def _run_migrations(
        self, *, db_url: str, engine: AsyncEngine, label: str
    ) -> None:
        cfg = Config(str(self.alembic_ini_path))
        cfg.set_main_option("sqlalchemy.url", db_url)
        cfg.set_main_option("script_location", str(self.alembic_script_location))
        # Ne pas laisser Alembic reconfigurer les logs
        cfg.attributes["skip_file_config"] = True

        before = await self._get_db_revision(engine)

        logger.info(
            "Démarrage des migrations Alembic %s -> head (rév. avant: %s)",
            label,
            before or "<base>",
        )

        # Upgrade (bloquant, dans un thread) + timeout
        await asyncio.wait_for(
            asyncio.to_thread(command.upgrade, cfg, "head"), timeout=300
        )

        after = await self._get_db_revision(engine)

        if before == after:
            logger.info(
                "Aucune migration à appliquer %s (DB déjà à jour). Rév. courante: %s",
                label,
                after or "<base>",
            )
        else:
            applied = self._revisions_between(cfg, lower=before, upper=after)
            if applied:
                logger.info(
                    "Migrations appliquées %s (%d): %s",
                    label,
                    len(applied),
                    ", ".join(applied),
                )
            else:
                logger.info(
                    "Migrations appliquées %s (bornes): %s -> %s",
                    label,
                    before or "<base>",
                    after or "<inconnue>",
                )

        logger.info(
            "Révision %s avant: %s | après: %s",
            label,
            before or "<base>",
            after or "<inconnue>",
        )
        logger.info("Migrations Alembic %s terminées avec succès ✅", label)

    async def auto_migrate(self) -> None:
        await self._run_migrations(
            db_url=database_settings.get_database_url(async_connection=True),
            engine=database_manager.async_engine,
            label="(base applicative)",
        )

    async def auto_migrate_analytics(self) -> None:
        """Applique la même chaîne de migrations à la base analytics.
        Le schéma complet est créé (dont des tables non répliquées qui restent
        vides), garantissant une parité stricte pour organization et
        event_store. Ignoré silencieusement si la base analytics n'est pas
        configurée (ex: environnement local).
        """
        if not analytics_database_settings.is_configured():
            logger.info(
                "Base analytics non configurée (ANALYTICS_*), migration ignorée."
            )
            return

        analytics_manager = get_analytics_database_manager()
        await self._run_migrations(
            db_url=analytics_database_settings.get_database_url(
                async_connection=True
            ),
            engine=analytics_manager.async_engine,
            label="(base analytics)",
        )

migration_service = MigrationService()
