class S3AuthentificationException(Exception):
    """Exception raised for errors in the OpenAI authentication process."""

    def __init__(
        self,
        message: str = "S3 authentication failed. Please check your API key and permissions.",
    ):
        self.message = message
        super().__init__(self.message)
