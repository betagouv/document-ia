from document_ia_infra.exception.retryable_exception import RetryableException


class WorkflowStepException(Exception):
    def __init__(self, step_name: str, inner_exception: Exception):
        self.step_name = step_name
        self.inner_exception = inner_exception
        super().__init__(f"Error in workflow step {step_name}: {inner_exception}")

    @staticmethod
    def is_retryable_exception(exception: Exception):
        if isinstance(exception, WorkflowStepException) and isinstance(
            exception.inner_exception, RetryableException
        ):
            return True
        return False
