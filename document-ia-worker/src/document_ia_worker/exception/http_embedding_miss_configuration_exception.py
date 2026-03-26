class HTTPEmbeddingMissConfigurationException(Exception):
    def __init__(self, embedding_service_name: str):
        self.embedding_service_name = embedding_service_name
        super().__init__(
            f"Embedding Service {embedding_service_name} miss configuration"
        )
