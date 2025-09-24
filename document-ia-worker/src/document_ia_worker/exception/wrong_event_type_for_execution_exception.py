class WrongEventTypeForExecutionException(Exception):
    def __init__(self, execution_id: str, event_type: str):
        self.execution_id = execution_id
        self.event_type = event_type
        super().__init__(
            f"Wrong event type {event_type}, attached to execution with ID: {execution_id}"
        )
