import logging
import sys
import time

from document_ia_auto_scaler.config.logging import setup_logging
from document_ia_auto_scaler.config.settings import settings
from document_ia_auto_scaler.scaler import QueueAutoScaler
from document_ia_auto_scaler.service.app_health import AppHealthService
from document_ia_auto_scaler.service.scalingo import ScalingoService

# Configuration des loggers
setup_logging()
logger = logging.getLogger("autoscaler")


def run_loop() -> None:
    logger.info("Démarrage du Daemon Autoscaler...")
    logger.info(
        "Configuration : MIN_WORKERS=%d, MAX_WORKERS=%d, THREAD_PER_WORKER=%d",
        settings.MIN_WORKERS,
        settings.MAX_WORKERS,
        settings.THREAD_PER_WORKER,
    )

    # Initialisation et vérification des configurations requises
    api_token = settings.SCALINGO_API_TOKEN
    app_name = settings.SCALINGO_APP_NAME
    health_url = settings.API_HEALTH_URL

    if not api_token or not app_name or not health_url:
        logger.error(
            "Erreur : SCALINGO_API_TOKEN, SCALINGO_APP_NAME et API_HEALTH_URL doivent être définies."
        )
        sys.exit(1)

    scalingo_service = ScalingoService(
        api_token=api_token,
        app_name=app_name,
        api_url=str(settings.SCALINGO_API_URL),
        auth_url=str(settings.SCALINGO_AUTH_URL),
    )
    health_service = AppHealthService(health_url=str(health_url))

    scaler = QueueAutoScaler(
        min_workers=settings.MIN_WORKERS,
        max_workers=settings.MAX_WORKERS,
        thread_per_worker=settings.THREAD_PER_WORKER,
        scale_up_cooldown=settings.SCALE_UP_COOLDOWN,
        scale_down_cooldown=settings.SCALE_DOWN_COOLDOWN,
    )

    last_scale_time = 0.0

    while True:
        try:
            # 1. Lecture du lag de queue Redis
            lag = health_service.get_queue_lag()
            if lag is None:
                logger.warning("Lag illisible, pas d'action prise pour ce cycle.")
                time.sleep(settings.CHECK_INTERVAL)
                continue

            # 2. Lecture du nombre d'instances de workers Scalingo
            current_w = scalingo_service.get_number_workers()
            if current_w is None:
                logger.warning(
                    "Nombre actuel de workers illisible, pas d'action prise pour ce cycle."
                )
                time.sleep(settings.CHECK_INTERVAL)
                continue

            # Log de statut régulier pour le dashboard Kibana
            logger.info(
                "Autoscaler status - Workers actuels : %d | Lag : %d", current_w, lag
            )

            now = time.time()

            # 3. Évaluation de la charge par le contrôleur
            decision = scaler.evaluate(
                current_time=now,
                last_scale_time=last_scale_time,
                current_workers=current_w,
                queue_lag=lag,
            )

            # 4. Exécution de l'action de scaling si nécessaire
            if decision:
                action, target_count = decision
                if action in ("scale_up", "scale_down"):
                    if scalingo_service.scale_workers(target_count):
                        last_scale_time = now
            else:
                logger.info(
                    "Aucune action de scaling. Workers actuels : %d | Lag : %d",
                    current_w,
                    lag,
                )

        except Exception as e:
            logger.error(
                "Erreur inattendue dans la boucle principale : %s", e, exc_info=True
            )

        time.sleep(settings.CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        run_loop()
    except KeyboardInterrupt:
        logger.info("Arrêt de l'autoscaler suite à un signal utilisateur.")
        sys.exit(0)
