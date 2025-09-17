class NoEventAttachedToExecutionException(Exception):
    """Raised when there is no event attached to the execution."""

    def __init__(self, execution_id: str):
        self.execution_id = execution_id
        super().__init__(f"No event attached to execution with ID: {execution_id}")
