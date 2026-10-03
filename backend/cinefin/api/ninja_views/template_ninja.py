import logging
from typing import Literal

from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest
from ninja import Field, Query, Router, Schema, Status

from cinefin.api.exceptions import ValidationError, get_or_404
from cinefin.api.models import (
    Bumper,
    Command,
    ProgrammeTemplate,
    ProgrammeTemplateItem,
    Tag,
    Trailer,
    TrailerTag,
)
from cinefin.api.schemas.base import ErrorResponseSchema, MessageResponseSchema, SuccessResponseSchema

logger = logging.getLogger(__name__)


class CommandBasicSchema(Schema):
    id: int
    name: str
    provider: str


class BumperBasicSchema(Schema):
    id: int
    title: str
    duration: float
    tags: list[str]


class TrailerBasicSchema(Schema):
    id: int
    title: str
    year: int | None = None
    content_rating: str = ""


class TagBasicSchema(Schema):
    id: int
    name: str


class TemplateItemSchema(Schema):
    id: int
    item_type: str = Field(..., description="feature, trailer_rule, command, etc.")
    order: int
    feature_number: int | None = None
    bound_to_feature: int | None = None
    trailer_count: int | None = 3
    match_genre: bool = True
    match_certification: bool = True
    match_year: bool = False
    year_delta: int | None = 5
    certification_feature: int | None = None
    count: int = 1
    command: CommandBasicSchema | None = None
    hold_black: bool = Field(False, description="Command items: hold a black screen for the command's duration")
    bumper: BumperBasicSchema | None = None
    trailer: TrailerBasicSchema | None = None
    tag: TagBasicSchema | None = None
    trailer_tag: TagBasicSchema | None = Field(
        None, description="Trailer-tag filter for trailer rules (trailer-library vocabulary)"
    )
    credits_command: CommandBasicSchema | None = Field(
        None, description="Command to execute when credits begin (for feature items)"
    )


class TemplateSchema(Schema):
    id: int
    name: str
    description: str
    number_of_features: int
    created_at: str
    items: list[TemplateItemSchema]


class TemplateSummarySchema(Schema):
    id: int
    name: str
    description: str
    number_of_features: int
    items_count: int
    item_types: list[str] = []
    created_at: str


class TemplatePaginationSchema(Schema):
    page: int
    per_page: int
    total: int
    total_pages: int


class TemplateListDataSchema(Schema):
    templates: list[TemplateSummarySchema]
    pagination: TemplatePaginationSchema


class TemplateListResponseSchema(SuccessResponseSchema):
    data: TemplateListDataSchema


class CreateTemplateItemSchema(Schema):
    item_type: Literal["feature", "trailer_rule", "command", "bumper", "trailer", "certification", "audio_bumper"]
    order: int = 0
    feature_number: int | None = None
    bound_to_feature: int | None = None
    trailer_count: int | None = 3
    match_genre: bool = True
    match_certification: bool = True
    match_year: bool = False
    year_delta: int | None = 5
    certification_feature: int | None = None
    count: int = 1
    command_id: int | None = None
    hold_black: bool = Field(False, description="Command items: hold a black screen for the command's duration")
    bumper_id: int | None = None
    trailer_id: int | None = None
    tag_id: int | None = None
    trailer_tag_id: int | None = Field(None, description="The trailer tag filtering a trailer rule's candidates")
    credits_command_id: int | None = Field(None, description="Command to execute when credits begin (feature items)")


class CreateTemplateSchema(Schema):
    name: str
    description: str | None = ""
    number_of_features: int = 1
    items: list[CreateTemplateItemSchema]


class UpdateTemplateSchema(Schema):
    name: str | None = None
    description: str | None = None
    number_of_features: int | None = None
    items: list[CreateTemplateItemSchema] | None = None


class TemplateDataSchema(Schema):
    id: int
    name: str
    template: TemplateSchema | None = None


class TemplateResponseSchema(SuccessResponseSchema):
    data: TemplateDataSchema


class TemplateListFilters(Schema):
    search: str | None = None
    page: int = 1
    per_page: int = 20


template_api = Router()

_NOT_FOUND = ("Template not found", "TEMPLATE_NOT_FOUND")


def serialize_command_basic(command: Command) -> CommandBasicSchema:
    return CommandBasicSchema(id=command.id, name=command.name, provider=command.provider)


def serialize_template(template: ProgrammeTemplate) -> TemplateSchema:
    items = [
        TemplateItemSchema(
            id=item.id,
            item_type=item.item_type,
            order=item.order,
            feature_number=item.feature_number,
            bound_to_feature=item.bound_to_feature,
            trailer_count=item.trailer_count or 3,
            match_genre=item.match_genre,
            match_certification=item.match_certification,
            match_year=item.match_year,
            year_delta=item.year_delta or 5,
            certification_feature=item.certification_feature,
            count=item.count,
            command=serialize_command_basic(item.command) if item.command else None,
            hold_black=item.hold_black,
            bumper=BumperBasicSchema(
                id=item.bumper.id,
                title=item.bumper.title,
                duration=item.bumper.duration,
                tags=[tag.name for tag in item.bumper.tags.all()],
            )
            if item.bumper
            else None,
            trailer=TrailerBasicSchema(
                id=item.trailer.id,
                title=item.trailer.title,
                year=item.trailer.year,
                content_rating=item.trailer.content_rating or "",
            )
            if item.trailer
            else None,
            tag=TagBasicSchema(id=item.tag.id, name=item.tag.name) if item.tag else None,
            trailer_tag=TagBasicSchema(id=item.trailer_tag.id, name=item.trailer_tag.name)
            if item.trailer_tag
            else None,
            credits_command=serialize_command_basic(item.credits_command) if item.credits_command else None,
        )
        for item in template.items.all().order_by("order")
    ]
    return TemplateSchema(
        id=template.id,
        name=template.name,
        description=template.description or "",
        number_of_features=template.number_of_features,
        created_at=template.created_at.isoformat(),
        items=items,
    )


# (field on the item, model, model field, error message noun, error code)
_ITEM_REFS = (
    ("command_id", Command, "command", "Command", "COMMAND_NOT_FOUND"),
    ("bumper_id", Bumper, "bumper", "User media item", "BUMPER_NOT_FOUND"),
    ("trailer_id", Trailer, "trailer", "Trailer", "TRAILER_NOT_FOUND"),
    ("tag_id", Tag, "tag", "Tag", "TAG_NOT_FOUND"),
    ("trailer_tag_id", TrailerTag, "trailer_tag", "Trailer tag", "TRAILER_TAG_NOT_FOUND"),
    ("credits_command_id", Command, "credits_command", "Command", "CREDITS_COMMAND_NOT_FOUND"),
)

_ITEM_FIELDS = (
    "item_type",
    "order",
    "feature_number",
    "bound_to_feature",
    "trailer_count",
    "match_genre",
    "match_certification",
    "match_year",
    "year_delta",
    "certification_feature",
    "count",
    "hold_black",
)


def _create_items(template: ProgrammeTemplate, items: list[CreateTemplateItemSchema]) -> None:
    for item in items:
        fields = {name: getattr(item, name) for name in _ITEM_FIELDS}
        for attr, model, field, noun, code in _ITEM_REFS:
            pk = getattr(item, attr)
            if pk:
                fields[field] = get_or_404(model, pk, f"{noun} {pk} not found", code)
        ProgrammeTemplateItem.objects.create(template=template, **fields)


def _saved(status: int, message: str, template: ProgrammeTemplate) -> Status:
    return Status(
        status, TemplateResponseSchema(message=message, data=TemplateDataSchema(id=template.id, name=template.name))
    )


@template_api.get("/list", response={200: TemplateListResponseSchema, 500: ErrorResponseSchema})
def list_templates(request: HttpRequest, filters: TemplateListFilters = Query(...)):
    per_page = min(filters.per_page, 100)
    offset = (filters.page - 1) * per_page
    templates = ProgrammeTemplate.objects.all()
    if filters.search:
        templates = templates.filter(Q(name__icontains=filters.search) | Q(description__icontains=filters.search))
    total_count = templates.count()
    return Status(
        200,
        TemplateListResponseSchema(
            message="Templates retrieved successfully",
            data=TemplateListDataSchema(
                templates=[
                    TemplateSummarySchema(
                        id=t.id,
                        name=t.name,
                        description=t.description or "",
                        number_of_features=t.number_of_features,
                        items_count=t.items.count(),
                        item_types=list(t.items.order_by("order").values_list("item_type", flat=True)),
                        created_at=t.created_at.isoformat(),
                    )
                    for t in templates.order_by("-created_at")[offset : offset + per_page]
                ],
                pagination=TemplatePaginationSchema(
                    page=filters.page,
                    per_page=per_page,
                    total=total_count,
                    total_pages=(total_count + per_page - 1) // per_page,
                ),
            ),
        ),
    )


_WRITE_ERRORS = {400: ErrorResponseSchema, 404: ErrorResponseSchema, 422: ErrorResponseSchema, 500: ErrorResponseSchema}


@template_api.post("/create", response={201: TemplateResponseSchema, **_WRITE_ERRORS})
def create_template(request: HttpRequest, data: CreateTemplateSchema):
    if not data.name.strip():
        raise ValidationError("Template name is required", error_code="TEMPLATE_NAME_REQUIRED")
    with transaction.atomic():
        template = ProgrammeTemplate.objects.create(
            name=data.name.strip(), description=data.description or "", number_of_features=data.number_of_features
        )
        _create_items(template, data.items)
    return _saved(201, "Template created successfully", template)


@template_api.post(
    "/{template_id}/duplicate",
    response={201: TemplateResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def duplicate_template(request: HttpRequest, template_id: int):
    original = get_or_404(ProgrammeTemplate, template_id, *_NOT_FOUND)
    with transaction.atomic():
        copy = ProgrammeTemplate.objects.create(
            name=f"{original.name} (copy)",
            description=original.description,
            is_default=False,
            number_of_features=original.number_of_features,
            trailer_count_per_feature=original.trailer_count_per_feature,
        )
        for item in original.items.all().order_by("order"):
            item.pk = None
            item.id = None
            item._state.adding = True
            item.template = copy
            item.save()
    return _saved(201, "Template duplicated successfully", copy)


@template_api.get(
    "/{template_id}", response={200: TemplateResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema}
)
def get_template_detail(request: HttpRequest, template_id: int):
    template = get_or_404(ProgrammeTemplate, template_id, *_NOT_FOUND)
    return Status(
        200,
        TemplateResponseSchema(
            message="Template retrieved successfully",
            data=TemplateDataSchema(id=template.id, name=template.name, template=serialize_template(template)),
        ),
    )


@template_api.put("/{template_id}", response={200: TemplateResponseSchema, **_WRITE_ERRORS})
def update_template(request: HttpRequest, template_id: int, data: UpdateTemplateSchema):
    with transaction.atomic():
        template = get_or_404(ProgrammeTemplate, template_id, *_NOT_FOUND)
        if data.name is not None:
            if not data.name.strip():
                raise ValidationError("Template name cannot be empty", error_code="TEMPLATE_NAME_EMPTY")
            template.name = data.name.strip()
        if data.description is not None:
            template.description = data.description
        if data.number_of_features is not None:
            template.number_of_features = data.number_of_features
        template.save()
        if data.items is not None:
            template.items.all().delete()
            _create_items(template, data.items)
    return _saved(200, "Template updated successfully", template)


@template_api.delete(
    "/{template_id}", response={200: MessageResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema}
)
def delete_template(request: HttpRequest, template_id: int):
    template = get_or_404(ProgrammeTemplate, template_id, *_NOT_FOUND)
    template.delete()
    return Status(200, MessageResponseSchema(message=f'Template "{template.name}" deleted successfully'))
