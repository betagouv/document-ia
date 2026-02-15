class LLMExtractionFailureException(Exception):
    """Exception raised when extraction llm return failure"""

    def __init__(
        self,
        message: str,
    ):
        self.message = message
        super().__init__(self.message)
