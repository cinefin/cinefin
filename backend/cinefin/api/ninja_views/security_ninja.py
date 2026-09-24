"""Security API — the optional single-user auth gate. Lockout-safe: auth can only be turned ON once a usable account exists; OFF is always allowed."""

import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpRequest
from ninja import Field, Router, Schema, Status

from cinefin.api.exceptions import NotFoundError, ValidationError
from cinefin.api.models import APIKey, Settings
from cinefin.api.schemas.base import ErrorResponseSchema, MessageResponseSchema, SuccessResponseSchema
from cinefin.api.services import auth_service

logger = logging.getLogger(__name__)

security_api = Router()


class SecurityStateSchema(Schema):
    auth_enabled: bool = Field(description="Whether the auth gate is switched on in settings")
    auth_active: bool = Field(description="Whether it is actually enforced right now (fail-open aware)")
    kiosk_public: bool = Field(description="Whether /kiosk/ stays reachable without logging in")
    has_account: bool = Field(description="Whether a usable account exists")
    username: str | None = Field(default=None, description="The single account's username, if any")


class SecurityStateResponse(SuccessResponseSchema):
    data: SecurityStateSchema


class SetPasswordInput(Schema):
    password: str = Field(..., description="New password (validated by Django's password validators)")
    confirm: str | None = Field(default=None, description="Optional confirmation; must match password if given")
    username: str | None = Field(default=None, description="Account username (defaults to 'admin' / current)")
    enable_auth: bool = Field(default=False, description="Also switch the auth gate on after setting the password")


class SecurityToggleInput(Schema):
    auth_enabled: bool | None = Field(default=None, description="Turn the auth gate on/off")
    kiosk_public: bool | None = Field(default=None, description="Allow the kiosk page without a login")


def _state() -> SecurityStateSchema:
    user = auth_service.get_single_user()
    has_account = auth_service.has_usable_account()
    return SecurityStateSchema(
        auth_enabled=bool(Settings.get("security.auth_enabled")),
        auth_active=auth_service.auth_is_active(),
        kiosk_public=bool(Settings.get("security.kiosk_public")),
        has_account=has_account,
        username=user.username if user else None,
    )


@security_api.get("/", response={200: SecurityStateResponse})
def get_security(request: HttpRequest):
    return Status(200, SecurityStateResponse(message="Security state", data=_state()))


@security_api.post("/set-password", response={200: SecurityStateResponse, 400: ErrorResponseSchema})
def set_password(request: HttpRequest, data: SetPasswordInput):
    """Create or update the single account's password (optionally enabling the auth gate)."""
    if data.confirm is not None and data.confirm != data.password:
        raise ValidationError("Passwords do not match", details={"field": "confirm"})
    try:
        user = auth_service.set_password(data.password, username=data.username)
    except DjangoValidationError as e:
        raise ValidationError("; ".join(e.messages), details={"field": "password"}) from None

    if data.enable_auth:
        auth_service.enable_auth()

    logger.info("Auth account password updated for '%s' (enable_auth=%s)", user.username, data.enable_auth)
    return Status(200, SecurityStateResponse(message="Password saved", data=_state()))


@security_api.post("/toggle", response={200: SecurityStateResponse, 400: ErrorResponseSchema})
def toggle_security(request: HttpRequest, data: SecurityToggleInput):
    """Toggle auth_enabled / kiosk_public (enabling auth without an account is refused)."""
    if data.kiosk_public is not None:
        Settings.set("security.kiosk_public", bool(data.kiosk_public))

    if data.auth_enabled is not None:
        if data.auth_enabled:
            try:
                auth_service.enable_auth()
            except DjangoValidationError as e:
                raise ValidationError("; ".join(e.messages), details={"field": "auth_enabled"}) from None
        else:
            auth_service.disable_auth()

    return Status(200, SecurityStateResponse(message="Security settings updated", data=_state()))


# API keys — bearer tokens authorising as the single account; only bite while the auth gate is on.
class APIKeySchema(Schema):
    id: int
    name: str
    prefix: str = Field(description="Display prefix, e.g. cplx_a1b2c3d4 (never the full key)")
    created_at: str
    last_used_at: str | None = Field(default=None)


class APIKeyListResponse(SuccessResponseSchema):
    data: list[APIKeySchema]


class CreateAPIKeyInput(Schema):
    name: str = Field(..., description="Human label for the key")


class CreatedAPIKeySchema(APIKeySchema):
    key: str = Field(description="The full key — shown ONCE, at creation, and never again")


class CreateAPIKeyResponse(SuccessResponseSchema):
    data: CreatedAPIKeySchema


def _key_schema(key: APIKey) -> APIKeySchema:
    return APIKeySchema(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        created_at=key.created_at.isoformat(),
        last_used_at=key.last_used_at.isoformat() if key.last_used_at else None,
    )


@security_api.get("/api-keys", response={200: APIKeyListResponse})
def list_api_keys(request: HttpRequest):
    """List the API keys (metadata only — the secret is unrecoverable)."""
    keys = [_key_schema(k) for k in APIKey.objects.all()]
    return Status(200, APIKeyListResponse(message="API keys", data=keys))


@security_api.post("/api-keys", response={200: CreateAPIKeyResponse, 400: ErrorResponseSchema})
def create_api_key(request: HttpRequest, data: CreateAPIKeyInput):
    """Mint a new API key. The full key is returned once here and never again."""
    name = (data.name or "").strip()
    if not name:
        raise ValidationError("Name is required", details={"field": "name"})
    key, raw_key = APIKey.create(name)
    logger.info("API key created: %s (%s)", key.name, key.prefix)
    payload = _key_schema(key).dict()
    payload["key"] = raw_key
    return Status(200, CreateAPIKeyResponse(message="API key created", data=CreatedAPIKeySchema(**payload)))


@security_api.delete("/api-keys/{key_id}", response={200: MessageResponseSchema, 404: ErrorResponseSchema})
def delete_api_key(request: HttpRequest, key_id: int):
    """Revoke (delete) an API key. It stops working immediately."""
    try:
        key = APIKey.objects.get(pk=key_id)
    except APIKey.DoesNotExist:
        raise NotFoundError("API key not found") from None
    label = key.name
    key.delete()
    logger.info("API key revoked: %s", label)
    return Status(200, MessageResponseSchema(message=f"API key '{label}' revoked"))
