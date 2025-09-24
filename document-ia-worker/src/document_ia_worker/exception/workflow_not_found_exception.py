class WorkflowNotFoundException(Exception):
    def __init__(self, workflow_id: str):
        self.workflow_id = workflow_id
        super().__init__(f"Workflow {workflow_id} not found")
