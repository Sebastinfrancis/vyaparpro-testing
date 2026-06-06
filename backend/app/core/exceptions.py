"""
VyaparPro — Custom Exception Hierarchy
All domain exceptions inherit from VyaparProError so handlers catch them centrally.
"""
from __future__ import annotations

from http import HTTPStatus


class VyaparProError(Exception):
    """Base exception for all VyaparPro errors."""
    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR.value
    error_code: str = "INTERNAL_ERROR"
    message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None, **kwargs: object) -> None:
        self.message = message or self.__class__.message
        self.detail = kwargs
        super().__init__(self.message)


# ── Auth Errors ──────────────────────────────────────────────────────────────
class AuthError(VyaparProError):
    status_code = 401
    error_code = "AUTH_ERROR"
    message = "Authentication failed."


class InvalidCredentialsError(AuthError):
    error_code = "INVALID_CREDENTIALS"
    message = "Invalid email or password."


class TokenExpiredError(AuthError):
    error_code = "TOKEN_EXPIRED"
    message = "Token has expired. Please log in again."


class TokenInvalidError(AuthError):
    error_code = "TOKEN_INVALID"
    message = "Invalid token."


class TwoFactorRequiredError(AuthError):
    status_code = 403
    error_code = "2FA_REQUIRED"
    message = "Two-factor authentication required."


class TwoFactorInvalidError(AuthError):
    error_code = "2FA_INVALID"
    message = "Invalid 2FA code."


class AccountLockedError(AuthError):
    status_code = 423
    error_code = "ACCOUNT_LOCKED"
    message = "Account is locked due to too many failed login attempts."


class AccountInactiveError(AuthError):
    status_code = 403
    error_code = "ACCOUNT_INACTIVE"
    message = "Account is inactive. Contact your administrator."


# ── Permission Errors ────────────────────────────────────────────────────────
class PermissionDeniedError(VyaparProError):
    status_code = 403
    error_code = "PERMISSION_DENIED"
    message = "You do not have permission to perform this action."


class InsufficientRoleError(PermissionDeniedError):
    error_code = "INSUFFICIENT_ROLE"
    message = "Your role does not have the required permissions."


# ── Resource Errors ──────────────────────────────────────────────────────────
class NotFoundError(VyaparProError):
    status_code = 404
    error_code = "NOT_FOUND"
    message = "Resource not found."


class AlreadyExistsError(VyaparProError):
    status_code = 409
    error_code = "ALREADY_EXISTS"
    message = "Resource already exists."


class CompanyNotFoundError(NotFoundError):
    error_code = "COMPANY_NOT_FOUND"
    message = "Company not found."


class BranchNotFoundError(NotFoundError):
    error_code = "BRANCH_NOT_FOUND"
    message = "Branch not found."


class UserNotFoundError(NotFoundError):
    error_code = "USER_NOT_FOUND"
    message = "User not found."


class PartyNotFoundError(NotFoundError):
    error_code = "PARTY_NOT_FOUND"
    message = "Party (customer/vendor) not found."


class ProductNotFoundError(NotFoundError):
    error_code = "PRODUCT_NOT_FOUND"
    message = "Product not found."


# ── Validation Errors ────────────────────────────────────────────────────────
class ValidationError(VyaparProError):
    status_code = 422
    error_code = "VALIDATION_ERROR"
    message = "Validation failed."


class GSTINValidationError(ValidationError):
    error_code = "INVALID_GSTIN"
    message = "Invalid GSTIN format."


class PANValidationError(ValidationError):
    error_code = "INVALID_PAN"
    message = "Invalid PAN format."


class PasswordValidationError(ValidationError):
    error_code = "WEAK_PASSWORD"
    message = "Password does not meet strength requirements."


# ── Business Logic Errors ────────────────────────────────────────────────────
class BusinessError(VyaparProError):
    status_code = 400
    error_code = "BUSINESS_ERROR"
    message = "Business rule violation."


class InsufficientStockError(BusinessError):
    error_code = "INSUFFICIENT_STOCK"
    message = "Insufficient stock for the requested quantity."


class InvoiceAlreadyFinalizedError(BusinessError):
    error_code = "INVOICE_FINALIZED"
    message = "This invoice has already been finalized and cannot be edited."


# ── Rate Limit Errors ────────────────────────────────────────────────────────
class RateLimitExceededError(VyaparProError):
    status_code = 429
    error_code = "RATE_LIMIT_EXCEEDED"
    message = "Too many requests. Please try again later."


# ── External Service Errors ──────────────────────────────────────────────────
class ExternalServiceError(VyaparProError):
    status_code = 502
    error_code = "EXTERNAL_SERVICE_ERROR"
    message = "External service returned an error."
