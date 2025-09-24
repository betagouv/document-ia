class WorkflowStepException(Exception):
    def __init__(self, step_name: str, inner_exception: Exception):
        self.step_name = step_name
        self.inner_exception = inner_exception
        super().__init__(f"Error in workflow step {step_name}: {inner_exception}")
