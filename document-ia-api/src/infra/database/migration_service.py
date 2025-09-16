import asyncio
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.exc import ProgrammingError

from infra.config import settings
from infra.database.database import async_engine

logger = logging.getLogger(__name__)


class MigrationService:
    def __init__(self):
        project_root = Path(__file__).resolve().parents[3]
        self.alembic_ini_path = project_root / "alembic.ini"
        self.alembic_script_location = project_root / "alembic"

    async def _get_db_revision(self) -> str | None:
        """Retourne la révision Alembic en DB (ou None si table absente)."""
        async with async_engine.connect() as conn:
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

    async def auto_migrate(self) -> None:
        cfg = Config(str(self.alembic_ini_path))
        cfg.set_main_option(
            "sqlalchemy.url", settings.get_database_url(async_connection=True)
        )
        cfg.set_main_option("script_location", str(self.alembic_script_location))
        # Ne pas laisser Alembic reconfigurer les logs
        cfg.attributes["skip_file_config"] = True

        before = await self._get_db_revision()

        logger.info(
            "Démarrage des migrations Alembic -> head (rév. avant: %s)",
            before or "<base>",
        )

        # Upgrade (bloquant, dans un thread) + timeout
        await asyncio.wait_for(
            asyncio.to_thread(command.upgrade, cfg, "head"), timeout=300
        )

        after = await self._get_db_revision()

        if before == after:
            logger.info(
                "Aucune migration à appliquer (DB déjà à jour). Rév. courante: %s",
                after or "<base>",
            )
        else:
            applied = self._revisions_between(cfg, lower=before, upper=after)
            if applied:
                logger.info(
                    "Migrations appliquées (%d): %s", len(applied), ", ".join(applied)
                )
            else:
                logger.info(
                    "Migrations appliquées (bornes): %s -> %s",
                    before or "<base>",
                    after or "<inconnue>",
                )

        logger.info(
            "Révision avant: %s | après: %s", before or "<base>", after or "<inconnue>"
        )
        logger.info("Migrations Alembic terminées avec succès ✅")


migration_service = MigrationService()
