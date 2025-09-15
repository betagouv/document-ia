"""
Classe Consumer commune pour les consumers Redis Stream
"""

import redis
import json
import time

import logging

logger = logging.getLogger(__name__)


class Consumer:
    def __init__(
        self,
        redis_client,
        process_callback,
        consumer_name,
        consumer_group,
        stream_name,
        batch_size,
        block_time,
    ):
        """Initialise la connexion Redis et le consumer"""
        self.consumer_name = consumer_name
        self.redis_client = redis_client
        self.stream_name = stream_name
        self.consumer_group = consumer_group

        # Callback function to process the message
        self.process_callback = process_callback

        # Configuration du consumer
        self.batch_size = batch_size
        self.block_time = block_time

        # Créer le consumer group s'il n'existe pas
        self._setup_consumer_group()

    def _setup_consumer_group(self):
        """
        Configure le consumer group pour le stream.

        Responsabilité du consumer : s'assurer que le consumer group existe
        avant de commencer à traiter les messages. Cela permet une séparation
        claire des responsabilités :
        - Publisher : publie des messages dans le stream
        - Consumer : gère le consumer group et traite les messages
        """
        try:
            # Créer le consumer group
            self.redis_client.xgroup_create(
                self.stream_name, self.consumer_group, id="0", mkstream=True
            )
            logger.info(f"✅ Consumer group '{self.consumer_group}' créé avec succès")
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                logger.info(f"ℹ️  Consumer group '{self.consumer_group}' existe déjà")
            else:
                logger.error(f"⚠️  Erreur lors de la création du consumer group: {e}")

    def run_consumer(self):
        """Lance le consumer pour traiter les messages du stream"""
        logger.info(f"\n🚀 Démarrage du Consumer: {self.consumer_name}")
        logger.info(f"📊 Stream: {self.stream_name}")
        logger.info(f"👥 Consumer Group: {self.consumer_group}")
        logger.info(
            f"⏱️  Block time: {self.block_time}ms | Batch size: {self.batch_size}\n"
        )

        while True:
            try:
                # Lire les messages du stream
                messages = self.redis_client.xreadgroup(
                    self.consumer_group,
                    self.consumer_name,
                    {self.stream_name: ">"},
                    count=self.batch_size,
                    block=self.block_time,
                )

                if messages:
                    for stream, stream_messages in messages:
                        logger.info(
                            f"📥 {self.consumer_name} reçoit: {len(stream_messages)} messages from {stream}"
                        )

                        for message_id, fields in stream_messages:
                            try:
                                # Extraire les données de la tâche
                                task_data = json.loads(fields.get("data", "{}"))

                                # Traiter la tâche
                                success, result = self.process_callback(task_data)

                                if success:
                                    logger.info(
                                        f"✅ {self.consumer_name} traite: {result}"
                                    )

                                    # Marquer le message comme traité
                                    self.acknowledge_message(message_id)
                                else:
                                    logger.error(
                                        f"❌ {self.consumer_name} échoue: {result}"
                                    )

                            except json.JSONDecodeError as e:
                                logger.error(f"❌ Erreur de décodage JSON: {e}")
                            except Exception as e:
                                logger.error(f"❌ Erreur de traitement: {e}")

            except redis.ConnectionError:
                logger.error("❌ Perte de connexion Redis, tentative de reconnexion...")
                time.sleep(5)
                continue

    def acknowledge_message(self, message_id):
        """Marque le message comme traité"""
        self.redis_client.xack(self.stream_name, self.consumer_group, message_id)
