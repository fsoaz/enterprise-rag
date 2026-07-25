from __future__ import annotations


class DomainError(Exception):
    """Base domain error. HTTP layer maps these to problem+json."""

    def __init__(self, message: str, *, type_slug: str = "internal-error") -> None:
        super().__init__(message)
        self.message = message
        self.type_slug = type_slug


class NotFoundError(DomainError):
    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__(message, type_slug="not-found")


class PermissionDeniedError(DomainError):
    def __init__(self, message: str = "Permission denied") -> None:
        super().__init__(message, type_slug="permission-denied")


class ValidationError(DomainError):
    def __init__(self, message: str, *, errors: list[dict[str, str]] | None = None) -> None:
        super().__init__(message, type_slug="validation-failed")
        self.errors = errors or []


class ConflictError(DomainError):
    def __init__(self, message: str = "Conflict") -> None:
        super().__init__(message, type_slug="conflict")


class QuotaExceededError(DomainError):
    def __init__(self, message: str = "Quota exceeded") -> None:
        super().__init__(message, type_slug="quota-exceeded")


class DependencyError(DomainError):
    def __init__(self, message: str, *, type_slug: str = "internal-error") -> None:
        super().__init__(message, type_slug=type_slug)


class RetrievalUnavailable(DependencyError):
    def __init__(self, message: str = "Retrieval unavailable") -> None:
        super().__init__(message, type_slug="retrieval-unavailable")


class InferenceUnavailable(DependencyError):
    def __init__(self, message: str = "Inference unavailable") -> None:
        super().__init__(message, type_slug="retrieval-unavailable")


class GenerationUnavailable(DependencyError):
    def __init__(self, message: str = "Generation unavailable") -> None:
        super().__init__(message, type_slug="generation-unavailable")
