import pytest

# Nous isolons l’engine/connection pool de SQLAlchemy par test pour éviter
# les conflits d’event loop (chaque test asyncio a sa propre event loop).
# Beaucoup de tests importent directement `database_manager` via :
#   from document_ia_infra.data.database import database_manager
# Ce binding se fait à l’import du module de test. On remplace donc à la fois
# l’attribut dans le module source et la variable globale du module de test.

import document_ia_infra.data.database as db_module
from document_ia_infra.data.database import DatabaseManager


@pytest.fixture(autouse=True)
async def isolated_database_manager(request):
    """Fournit un DatabaseManager neuf par test et remplace l’instance globale.

    - Crée un nouvel async_engine/async_sessionmaker par test (évite de réutiliser
      un pool attaché à une event loop précédente).
    - Remplace db_module.database_manager et, si présent, la variable
      `database_manager` du module de test.
    - Dispose proprement l’engine en fin de test.
    """
    manager = DatabaseManager()

    # Remplace l’instance globale du module source
    db_module.database_manager = manager

    # Si le module de test a son propre symbole `database_manager` (import direct),
    # on le remplace aussi pour que les fonctions utilisent le nouveau manager.
    test_mod = getattr(request.node, "module", None)
    if test_mod is not None and hasattr(test_mod, "database_manager"):
        setattr(test_mod, "database_manager", manager)

    try:
        yield manager
    finally:
        # Ferme proprement l’engine/pool pour éviter les handles ouverts
        try:
            await manager.async_engine.dispose()
        except Exception:
            pass
