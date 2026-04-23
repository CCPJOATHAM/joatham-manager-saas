class FacturationError(Exception):
    """Base exception for billing domain errors."""


class PermissionFacturationError(FacturationError):
    """Raised when a user role cannot perform a billing action."""


class WorkflowFacturationError(FacturationError):
    """Raised when a status transition is invalid."""


class PaiementFacturationError(FacturationError):
    """Raised when a payment operation violates billing rules."""
