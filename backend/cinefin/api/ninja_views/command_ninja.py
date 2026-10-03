"""Command API: CRUD and execution for provider-based commands, plus the provider catalogue
(the contrib plugins, see cinefin.plugins) the SPA renders its forms from.

Runs are not persisted: /test and /execute hand their result straight back to the caller.
"""

import logging
from collections import Counter
from typing import Any

from django.http import HttpRequest
from ninja import Field, Query, Router, Schema, Status

from cinefin import plugins
from cinefin.api.exceptions import ConflictError, ValidationError, get_or_404
from cinefin.api.models import Command, ProgrammeBlock, ProgrammeSchedule, ProgrammeTemplateItem
from cinefin.api.schemas.base import ErrorResponseSchema, MessageResponseSchema, SuccessResponseSchema
from cinefin.api.services import command_runner, preshow

logger = logging.getLogger(__name__)

# A provider id from the cinefin.plugins registry; validated against it, not a fixed Literal.
Provider = str


class CommandUsageSchema(Schema):
    """Where a command is referenced — shown in the UI and delete confirms."""

    programmes: int
    templates: int
    credits: int = Field(description="Blocks/items using it as a credits command")
    preshow: bool = Field(description="Whether an upcoming screening's lead-in runs it")


class CommandSchema(Schema):
    id: int
    name: str
    provider: Provider
    provider_label: str = Field(description="Provider display name (the id, if the provider is not loaded)")
    provider_icon: str = Field(description="Provider icon name (lucide)")
    summary: str = Field(description="One-line description of the command's target, from its provider")
    config: dict[str, Any] = Field(description="Provider-specific configuration")
    duration: float = Field(description="Duration in seconds that this command takes to execute")
    used_in: CommandUsageSchema = Field(description="Programmes/templates/credits/pre-show references")
    locked: bool = Field(description="A built-in command: only its duration can change; it can't be deleted")


class CreateCommandSchema(Schema):
    name: str = Field(min_length=1, max_length=255)
    provider: Provider = "rest"
    config: dict[str, Any] = Field(default_factory=dict, description="Provider-specific configuration")
    duration: float | None = Field(default=0.0, description="Duration in seconds that this command takes to execute")


class UpdateCommandSchema(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    provider: Provider | None = None
    config: dict[str, Any] | None = Field(default=None, description="Provider-specific configuration")
    duration: float | None = Field(default=None, description="Duration in seconds that this command takes to execute")


class TestCommandSchema(Schema):
    provider: Provider = "rest"
    config: dict[str, Any] = Field(default_factory=dict, description="Provider-specific configuration")


class CommandResultSchema(Schema):
    """The outcome of one execution (not stored: this is the only place it is reported)."""

    ok: bool
    detail: str = Field(description="Outcome summary, e.g. 'HTTP 200' or 'timeout'")
    output: str = Field(description="Captured output (truncated)")


class ProviderFieldSchema(Schema):
    key: str
    label: str
    type: str = Field(description="text | textarea | secret | number | boolean | select | json")
    required: bool
    default: Any = None
    placeholder: str
    help: str
    choices: list[str]
    scoped_by: str = Field(description="Filter this field's suggestions by the value of another field")


class ProviderSchema(Schema):
    id: str
    label: str
    icon: str
    description: str
    source: str
    enabled: bool = Field(description="False = hidden from the command picker and refuses to run")
    has_suggestions: bool = Field(description="Whether the command dialog should fetch autocomplete suggestions")
    has_settings_test: bool
    has_discover: bool = Field(description="Whether the provider can discover its settings on the network")
    builtin: bool = Field(description="Its commands are built in: none can be created for it")
    fields: list[ProviderFieldSchema] = Field(description="Per-command configuration fields")
    settings: list[ProviderFieldSchema] = Field(description="Provider-wide settings fields")


class PluginFailureSchema(Schema):
    source: str
    error: str


class ProviderListDataSchema(Schema):
    providers: list[ProviderSchema]
    failures: list[PluginFailureSchema]


class ProviderListResponseSchema(SuccessResponseSchema):
    data: ProviderListDataSchema


class SuggestionSchema(Schema):
    value: str
    label: str | None = None
    scope: str | None = None


class SuggestionsDataSchema(Schema):
    ok: bool = Field(description="False when the provider could not fetch its suggestions")
    message: str
    suggestions: dict[str, list[SuggestionSchema]]


class SuggestionsResponseSchema(SuccessResponseSchema):
    data: SuggestionsDataSchema


class ProviderSettingsDataSchema(Schema):
    values: dict[str, Any]


class ProviderSettingsResponseSchema(SuccessResponseSchema):
    data: ProviderSettingsDataSchema


class SettingsTestDataSchema(Schema):
    ok: bool
    message: str


class SettingsTestResponseSchema(SuccessResponseSchema):
    data: SettingsTestDataSchema


class DiscoveredSchema(Schema):
    label: str
    values: dict[str, Any] = Field(description="Settings values to fill in when the operator picks it")


class DiscoverDataSchema(Schema):
    candidates: list[DiscoveredSchema]


class DiscoverResponseSchema(SuccessResponseSchema):
    data: DiscoverDataSchema


class CommandListDataSchema(Schema):
    commands: list[CommandSchema]
    total: int


class CommandListResponseSchema(SuccessResponseSchema):
    data: CommandListDataSchema


class CommandCreateResponseSchema(SuccessResponseSchema):
    data: CommandSchema


class RunResultDataSchema(Schema):
    result: CommandResultSchema


class RunResultResponseSchema(SuccessResponseSchema):
    data: RunResultDataSchema


class CommandListFilters(Schema):
    type: Provider | None = None
    search: str | None = None


command_api = Router()


def _get_provider(provider_id: str) -> plugins.CommandProvider:
    provider = plugins.get_provider(provider_id)
    if provider is None:
        raise ValidationError(f"Unknown command provider '{provider_id}'", error_code="UNKNOWN_PROVIDER")
    return provider


def _validate_config(provider_id: str, config: dict) -> None:
    problems = _get_provider(provider_id).validate_config(config)
    if problems:
        raise ValidationError(
            f"Invalid config for {provider_id} commands: {'; '.join(problems)}",
            error_code="INVALID_COMMAND_CONFIG",
        )


def _command_usage(commands: list[Command]) -> dict[int, CommandUsageSchema]:
    """Batch-compute where each command is referenced (no per-row queries)."""
    ids = [c.id for c in commands]
    if not ids:
        return {}

    programme_counts = Counter(
        command_id
        for command_id, _ in ProgrammeBlock.objects.filter(command_id__in=ids)
        .values_list("command_id", "programme_id")
        .distinct()
    )
    template_counts = Counter(
        command_id
        for command_id, _ in ProgrammeTemplateItem.objects.filter(command_id__in=ids)
        .values_list("command_id", "template_id")
        .distinct()
    )
    credits_counts = Counter(
        ProgrammeBlock.objects.filter(credits_command_id__in=ids).values_list("credits_command_id", flat=True)
    ) + Counter(
        ProgrammeTemplateItem.objects.filter(credits_command_id__in=ids).values_list("credits_command_id", flat=True)
    )
    preshow_ids = {
        cid
        for steps in ProgrammeSchedule.objects.filter(status="scheduled").values_list("preshow", flat=True)
        for cid in preshow.command_ids(steps)
    }

    return {
        command_id: CommandUsageSchema(
            programmes=programme_counts.get(command_id, 0),
            templates=template_counts.get(command_id, 0),
            credits=credits_counts.get(command_id, 0),
            preshow=command_id in preshow_ids,
        )
        for command_id in ids
    }


def serialize_command(command: Command, usage: dict[int, CommandUsageSchema] | None = None) -> CommandSchema:
    if usage is None:
        usage = _command_usage([command])
    provider = plugins.get_provider(command.provider)
    config = command.config or {}
    try:
        summary = provider.summary(config) if provider else ""
    except Exception:  # noqa: BLE001 - a plugin's summary bug must not break the list
        logger.exception("Provider %s failed to summarise command %s", command.provider, command.id)
        summary = ""
    return CommandSchema(
        id=command.id,
        name=command.name,
        provider=command.provider,
        provider_label=(provider.label or provider.id) if provider else command.provider,
        provider_icon=provider.icon if provider else "zap",
        summary=summary or "",
        config=config,
        duration=command.duration,
        used_in=usage.get(command.id) or CommandUsageSchema(programmes=0, templates=0, credits=0, preshow=False),
        locked=plugins.is_builtin(command.provider),
    )


def _result_response(message: str, result: command_runner.CommandResult) -> Status:
    return Status(
        200,
        RunResultResponseSchema(
            message=message,
            data=RunResultDataSchema(
                result=CommandResultSchema(ok=result.ok, detail=result.detail, output=result.output)
            ),
        ),
    )


@command_api.get("/list", response={200: CommandListResponseSchema, 500: ErrorResponseSchema})
def list_commands(request: HttpRequest, filters: CommandListFilters = Query(...)):
    commands = Command.objects.all().order_by("name")

    if filters.type:
        commands = commands.filter(provider=filters.type)
    if filters.search:
        commands = commands.filter(name__icontains=filters.search)
    commands = list(commands)
    usage = _command_usage(commands)
    serialized = [serialize_command(cmd, usage) for cmd in commands]
    return Status(
        200,
        CommandListResponseSchema(
            message="Commands retrieved successfully",
            data=CommandListDataSchema(commands=serialized, total=len(serialized)),
        ),
    )


@command_api.get("/providers", response={200: ProviderListResponseSchema})
def list_command_providers(request: HttpRequest):
    """The command providers (contrib plugins) loaded in this install, and any plugins that failed to load."""
    return Status(
        200,
        ProviderListResponseSchema(
            message="Providers retrieved successfully",
            data=ProviderListDataSchema(
                providers=[p.to_dict() for p in plugins.list_providers()],
                failures=plugins.load_failures(),
            ),
        ),
    )


@command_api.get(
    "/providers/{provider_id}/suggestions", response={200: SuggestionsResponseSchema, 400: ErrorResponseSchema}
)
def get_provider_suggestions(request: HttpRequest, provider_id: str):
    """Autocomplete values for the command dialog; an unreachable source is a result (ok=false), not an error."""
    provider = _get_provider(provider_id)
    try:
        raw = provider.suggestions(provider.load_settings()) or {}
        suggestions = {
            key: [
                SuggestionSchema(**{k: str(v) for k, v in item.items() if k in ("value", "label", "scope")})
                for item in items
            ]
            for key, items in raw.items()
        }
        ok, message = True, ""
    except Exception as exc:  # noqa: BLE001 - plugin code; report, never 500
        logger.info("Suggestions from %s failed: %s", provider_id, exc)
        suggestions, ok, message = {}, False, str(exc) or exc.__class__.__name__
    return Status(
        200,
        SuggestionsResponseSchema(
            message="Suggestions retrieved",
            data=SuggestionsDataSchema(ok=ok, message=message, suggestions=suggestions),
        ),
    )


@command_api.get(
    "/providers/{provider_id}/settings", response={200: ProviderSettingsResponseSchema, 400: ErrorResponseSchema}
)
def get_provider_settings(request: HttpRequest, provider_id: str):
    """A provider's saved settings (only providers that declare settings fields store any here)."""
    provider = _get_provider(provider_id)
    values = provider.load_settings() if provider.settings else {}
    return Status(
        200,
        ProviderSettingsResponseSchema(message="Settings retrieved", data=ProviderSettingsDataSchema(values=values)),
    )


@command_api.put(
    "/providers/{provider_id}/settings", response={200: ProviderSettingsResponseSchema, 400: ErrorResponseSchema}
)
def update_provider_settings(request: HttpRequest, provider_id: str, data: ProviderSettingsDataSchema):
    """Save a provider's settings; keys it does not declare are dropped."""
    provider = _get_provider(provider_id)
    if not provider.settings:
        raise ValidationError(f"Provider '{provider_id}' has no settings", error_code="NO_PROVIDER_SETTINGS")
    values = {f.key: data.values.get(f.key) for f in provider.settings if f.key in data.values}
    problems = provider.validate_settings(values)
    if problems:
        raise ValidationError("; ".join(problems), error_code="INVALID_PROVIDER_SETTINGS")
    provider.save_settings(values)
    return Status(
        200,
        ProviderSettingsResponseSchema(
            message=f"{provider.label} settings saved", data=ProviderSettingsDataSchema(values=provider.load_settings())
        ),
    )


class ProviderEnabledSchema(Schema):
    enabled: bool


@command_api.post("/providers/{provider_id}/enabled", response={200: MessageResponseSchema, 400: ErrorResponseSchema})
def set_provider_enabled(request: HttpRequest, provider_id: str, data: ProviderEnabledSchema):
    """Enable or disable a plugin (soft): a disabled provider is hidden from the command picker and refuses to run."""
    provider = _get_provider(provider_id)
    plugins.set_enabled(provider_id, data.enabled)
    return Status(200, MessageResponseSchema(message=f"{provider.label} {'enabled' if data.enabled else 'disabled'}"))


@command_api.post(
    "/providers/{provider_id}/settings/test",
    response={200: SettingsTestResponseSchema, 400: ErrorResponseSchema},
)
def test_provider_settings(request: HttpRequest, provider_id: str, data: ProviderSettingsDataSchema):
    """Check settings (typically unsaved form values) work; a failed check is a result (ok=false), not an error."""
    provider = _get_provider(provider_id)
    if not provider.supports("test_settings"):
        raise ValidationError(f"Provider '{provider_id}' cannot test its settings", error_code="NO_SETTINGS_TEST")
    try:
        ok, message = provider.test_settings(provider.load_settings() | data.values)
    except Exception as exc:  # noqa: BLE001 - plugin code; report, never 500
        logger.exception("Settings test for %s raised", provider_id)
        ok, message = False, f"{exc.__class__.__name__}: {exc}"
    return Status(
        200,
        SettingsTestResponseSchema(
            message="Settings test finished", data=SettingsTestDataSchema(ok=bool(ok), message=str(message))
        ),
    )


@command_api.get("/providers/{provider_id}/discover", response={200: DiscoverResponseSchema, 400: ErrorResponseSchema})
def discover_provider_settings(request: HttpRequest, provider_id: str):
    """Look for candidate settings on the local network (e.g. Home Assistant over mDNS)."""
    provider = _get_provider(provider_id)
    if not provider.supports("discover"):
        raise ValidationError(f"Provider '{provider_id}' cannot discover settings", error_code="NO_DISCOVERY")
    try:
        candidates = [
            DiscoveredSchema(label=str(c.get("label") or ""), values=dict(c.get("values") or {}))
            for c in provider.discover() or []
        ]
    except Exception:  # noqa: BLE001 - plugin code; nothing found beats a 500
        logger.exception("Discovery for %s raised", provider_id)
        candidates = []
    return Status(
        200, DiscoverResponseSchema(message="Discovery finished", data=DiscoverDataSchema(candidates=candidates))
    )


@command_api.post("/test", response={200: RunResultResponseSchema, 400: ErrorResponseSchema, 500: ErrorResponseSchema})
def test_command(request: HttpRequest, data: TestCommandSchema):
    """Test a command configuration without saving it (runs synchronously, returns output)."""
    _validate_config(data.provider, data.config)

    temp_command = Command(name="Test Command", provider=data.provider, config=data.config)
    result = command_runner.execute(temp_command, trigger="test", wait=True)
    return _result_response(f"Command test {'succeeded' if result.ok else 'failed'} ({result.detail})", result)


@command_api.post(
    "/create", response={201: CommandCreateResponseSchema, 400: ErrorResponseSchema, 500: ErrorResponseSchema}
)
def create_command(request: HttpRequest, data: CreateCommandSchema):
    name = data.name.strip()
    if not name:
        raise ValidationError("Command name is required")
    if Command.objects.filter(name=name).exists():
        raise ConflictError(f"A command named '{name}' already exists")
    if plugins.is_builtin(data.provider):
        raise ValidationError(f"'{data.provider}' commands are built in — they can't be created")
    _validate_config(data.provider, data.config)

    command = Command.objects.create(
        name=name, provider=data.provider, config=data.config, duration=data.duration or 0.0
    )
    return Status(
        201, CommandCreateResponseSchema(message="Command created successfully", data=serialize_command(command))
    )


@command_api.put(
    "/{command_id}/update",
    response={
        200: CommandCreateResponseSchema,
        400: ErrorResponseSchema,
        404: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def update_command(request: HttpRequest, command_id: int, data: UpdateCommandSchema):
    command = get_or_404(Command, command_id, "Command not found")
    locked = plugins.is_builtin(command.provider)
    if locked and (
        (data.name is not None and data.name.strip() != command.name)
        or (data.provider is not None and data.provider != command.provider)
        or (data.config is not None and data.config != command.config)
    ):
        raise ValidationError("A built-in command can't be renamed or reconfigured — only its duration can change")
    if not locked and data.provider is not None and plugins.is_builtin(data.provider):
        raise ValidationError(f"'{data.provider}' commands are built in — they can't be created")

    if data.name is not None:
        name = data.name.strip()
        if not name:
            raise ValidationError("Command name cannot be empty")
        if Command.objects.filter(name=name).exclude(pk=command.pk).exists():
            raise ConflictError(f"A command named '{name}' already exists")
        command.name = name

    if data.provider is not None:
        command.provider = data.provider
    if data.config is not None:
        command.config = data.config
    _validate_config(command.provider, command.config)

    if data.duration is not None:
        command.duration = data.duration

    command.save()
    return Status(
        200, CommandCreateResponseSchema(message="Command updated successfully", data=serialize_command(command))
    )


@command_api.delete(
    "/{command_id}/delete",
    response={200: MessageResponseSchema, 404: ErrorResponseSchema, 409: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def delete_command(request: HttpRequest, command_id: int):
    command = get_or_404(Command, command_id, "Command not found")
    if plugins.is_builtin(command.provider):
        raise ConflictError("A built-in command can't be deleted")
    command.delete()
    return Status(200, MessageResponseSchema(message=f'Command "{command.name}" deleted successfully'))


@command_api.post(
    "/{command_id}/execute",
    response={200: RunResultResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def execute_command(request: HttpRequest, command_id: int):
    """Execute a command (runs synchronously, returns its outcome and output)."""
    command = get_or_404(Command, command_id, "Command not found")
    result = command_runner.execute(command, trigger="remote", wait=True)

    return _result_response(
        f'Command "{command.name}" {"succeeded" if result.ok else "failed"} ({result.detail})', result
    )
