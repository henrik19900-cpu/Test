"""Domain errors. Services raise these; the API, MCP and web layers render them."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status = 400
    code = "bad_request"
    title = "Bad request"

    def __init__(
        self,
        message: str,
        *,
        errors: list[dict[str, Any]] | None = None,
        hint: str | None = None,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.errors = errors or []
        self.hint = hint
        self.headers = headers or {}

    def to_problem(self, instance: str | None = None) -> dict[str, Any]:
        """RFC 9457 problem details."""
        problem: dict[str, Any] = {
            "type": "about:blank",
            "title": self.title,
            "status": self.status,
            "detail": self.message,
            "code": self.code,
        }
        if instance:
            problem["instance"] = instance
        if self.errors:
            problem["errors"] = self.errors
        if self.hint:
            problem["hint"] = self.hint
        return problem


class ValidationProblem(AppError):
    status = 422
    code = "validation_error"
    title = "Validation error"

    @classmethod
    def field(cls, field: str, message: str, hint: str | None = None) -> ValidationProblem:
        return cls(f"{field}: {message}", errors=[{"field": field, "message": message}], hint=hint)

    @classmethod
    def from_errors(cls, errors: list[dict[str, Any]], hint: str | None = None) -> ValidationProblem:
        sentences = [
            e["message"] if e["message"].endswith((".", "?", "!")) else e["message"] + "." for e in errors
        ]
        return cls(" ".join(sentences), errors=errors, hint=hint)


class Unauthorized(AppError):
    status = 401
    code = "unauthorized"
    title = "Authentication required"


class Forbidden(AppError):
    status = 403
    code = "forbidden"
    title = "Forbidden"


class NotFound(AppError):
    status = 404
    code = "not_found"
    title = "Not found"


class Conflict(AppError):
    status = 409
    code = "conflict"
    title = "Conflict"


class PayloadTooLarge(AppError):
    status = 413
    code = "payload_too_large"
    title = "Payload too large"


class RateLimited(AppError):
    status = 429
    code = "rate_limited"
    title = "Too many requests"

    def __init__(self, message: str, *, retry_after: int, hint: str | None = None):
        super().__init__(message, hint=hint, headers={"Retry-After": str(max(1, retry_after))})
        self.retry_after = retry_after
