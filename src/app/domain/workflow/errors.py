"""Expected failures for controlled support workflows."""

from app.errors import DomainError


class WorkflowError(DomainError):
    """This error represents a safe workflow operation failure."""

    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(code=code, message=message, status_code=status_code)


class WorkflowNotFound(WorkflowError):
    def __init__(self) -> None:
        super().__init__("workflow_not_found", "The workflow does not exist.", 404)


class WorkflowExpired(WorkflowError):
    def __init__(self) -> None:
        super().__init__("workflow_expired", "The workflow confirmation has expired.", 409)


class InvalidWorkflowResume(WorkflowError):
    def __init__(self, message: str = "The workflow cannot be resumed.") -> None:
        super().__init__("invalid_workflow_resume", message, 409)


class WorkflowActorMismatch(WorkflowError):
    def __init__(self) -> None:
        super().__init__(
            "workflow_actor_mismatch",
            "The workflow actor does not match the confirmation request.",
            403,
        )


class TransientModelError(Exception):
    """A model failure that is safe for LangGraph to retry."""


class TransientRetrievalError(Exception):
    """A retrieval failure that is safe for LangGraph to retry."""


class UnsafeWorkflowError(Exception):
    """A permanent or unsafe condition that must be escalated."""
