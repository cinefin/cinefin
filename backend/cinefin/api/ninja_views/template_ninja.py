import logging
from typing import Literal

from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest
from ninja import Field, Query, Router, Schema, Status

from cinefin.api.exceptions import NotFoundError, ValidationError
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
    id: int = Field(..., description="Command ID")
    name: str = Field(..., description="Command name")
    provider: str = Field(..., description="Execution provider")


class BumperBasicSchema(Schema):
    id: int = Field(..., description="Bumper ID")
    title: str = Field(..., description="Bumper title")
    duration: float = Field(..., description="Bumper duration in seconds")
    tags: list[str] = Field(..., description="List of tag names")


class TrailerBasicSchema(Schema):
    id: int = Field(..., description="Trailer ID")
    title: str = Field(..., description="Trailer title")
    year: int | None = Field(None, description="Trailer release year")
    content_rating: str = Field("", description="Trailer content rating")


class TagBasicSchema(Schema):
    id: int = Field(..., description="Tag ID")
    name: str = Field(..., description="Tag name")


class TemplateContentSchema(Schema):
    commands: list[CommandBasicSchema]
    bumpers: list[BumperBasicSchema]
    tags: list[TagBasicSchema]


class TemplateItemSchema(Schema):
    id: int = Field(..., description="Template item ID")
    item_type: str = Field(..., description="Type of template item (feature, trailer_rule, command, etc.)")
    order: int = Field(..., description="Display order within template")
    feature_number: int | None = Field(None, description="Feature number this item is associated with")
    bound_to_feature: int | None = Field(None, description="Feature this item is bound to")
    trailer_count: int | None = Field(3, description="Number of trailers to include")
    match_genre: bool = Field(True, description="Whether to match genre when selecting trailers")
    match_certification: bool = Field(True, description="Whether to match certification when selecting trailers")
    match_year: bool = Field(False, description="Whether to match year when selecting trailers")
    year_delta: int | None = Field(5, description="Acceptable year difference for trailer matching")
    certification_feature: int | None = Field(None, description="Feature number for certification reference")
    count: int = Field(1, description="Number of items to include")
    command: CommandBasicSchema | None = Field(None, description="Associated command details")
    hold_black: bool = Field(False, description="Command items: hold a black screen for the command's duration")
    bumper: BumperBasicSchema | None = Field(None, description="Associated bumper details")
    trailer: TrailerBasicSchema | None = Field(None, description="Associated specific-trailer details")
    tag: TagBasicSchema | None = Field(None, description="Associated tag details")
    trailer_tag: TagBasicSchema | None = Field(
        None, description="Trailer-tag filter for trailer rules (trailer-library vocabulary)"
    )
    credits_command: CommandBasicSchema | None = Field(
        None, description="Command to execute when credits begin (for feature items)"
    )


class TemplateSchema(Schema):
    id: int = Field(..., description="Template ID")
    name: str = Field(..., description="Template name")
    description: str = Field(..., description="Template description")
    number_of_features: int = Field(..., description="Number of features this template supports")
    created_at: str = Field(..., description="Template creation timestamp in ISO format")
    items: list[TemplateItemSchema] = Field(..., description="List of template items")


class TemplateSummarySchema(Schema):
    id: int = Field(..., description="Template ID")
    name: str = Field(..., description="Template name")
    description: str = Field(..., description="Template description")
    number_of_features: int = Field(..., description="Number of features this template supports")
    items_count: int = Field(..., description="Total number of items in template")
    item_types: list[str] = Field([], description="Ordered item types, for structure previews")
    created_at: str = Field(..., description="Template creation timestamp in ISO format")


class TemplatePaginationSchema(Schema):
    page: int = Field(..., description="Current page number")
    per_page: int = Field(..., description="Items per page")
    total: int = Field(..., description="Total number of templates")
    total_pages: int = Field(..., description="Total number of pages")


class TemplateListDataSchema(Schema):
    templates: list[TemplateSummarySchema] = Field(..., description="List of templates")
    pagination: TemplatePaginationSchema = Field(..., description="Pagination information")


class TemplateListResponseSchema(SuccessResponseSchema):
    data: TemplateListDataSchema = Field(..., description="Template list data")


class CreateTemplateItemSchema(Schema):
    item_type: Literal["feature", "trailer_rule", "command", "bumper", "trailer", "certification", "audio_bumper"] = (
        Field(..., description="Type of template item")
    )
    order: int = Field(0, description="Display order within template")
    feature_number: int | None = Field(None, description="Feature number this item is associated with")
    bound_to_feature: int | None = Field(None, description="Feature this item is bound to")
    trailer_count: int | None = Field(3, description="Number of trailers to include")
    match_genre: bool = Field(True, description="Whether to match genre when selecting trailers")
    match_certification: bool = Field(True, description="Whether to match certification when selecting trailers")
    match_year: bool = Field(False, description="Whether to match year when selecting trailers")
    year_delta: int | None = Field(5, description="Acceptable year difference for trailer matching")
    certification_feature: int | None = Field(None, description="Feature number for certification reference")
    count: int = Field(1, description="Number of items to include")
    command_id: int | None = Field(None, description="ID of command to associate")
    hold_black: bool = Field(False, description="Command items: hold a black screen for the command's duration")
    bumper_id: int | None = Field(None, description="ID of bumper to associate")
    trailer_id: int | None = Field(None, description="ID of a specific trailer to associate")
    tag_id: int | None = Field(None, description="ID of tag to associate")
    trailer_tag_id: int | None = Field(None, description="ID of the trailer tag filtering a trailer rule's candidates")
    credits_command_id: int | None = Field(
        None, description="ID of command to execute when credits begin (for feature items)"
    )


class CreateTemplateSchema(Schema):
    name: str = Field(..., description="Template name")
    description: str | None = Field("", description="Template description")
    number_of_features: int = Field(1, description="Number of features this template supports")
    items: list[CreateTemplateItemSchema] = Field(..., description="List of template items to create")


class UpdateTemplateSchema(Schema):
    name: str | None = Field(None, description="Updated template name")
    description: str | None = Field(None, description="Updated template description")
    number_of_features: int | None = Field(None, description="Updated number of features")
    items: list[CreateTemplateItemSchema] | None = Field(None, description="Updated list of template items")


class TemplateDataSchema(Schema):
    id: int = Field(..., description="Template ID")
    name: str = Field(..., description="Template name")
    template: TemplateSchema | None = Field(None, description="Full template details")


class TemplateCreateResponseSchema(SuccessResponseSchema):
    data: TemplateDataSchema = Field(..., description="Created template data")


class TemplateDetailResponseSchema(SuccessResponseSchema):
    data: TemplateDataSchema = Field(..., description="Template details")


class TemplateListFilters(Schema):
    search: str | None = Field(None, description="Search term for template name or description")
    page: int = Field(1, description="Page number for pagination")
    per_page: int = Field(20, description="Number of items per page")


template_api = Router()


def serialize_command_basic(command: Command) -> CommandBasicSchema:
    return CommandBasicSchema(id=command.id, name=command.name, provider=command.provider)


def serialize_bumper_basic(bumper: Bumper) -> BumperBasicSchema:
    return BumperBasicSchema(
        id=bumper.id, title=bumper.title, duration=bumper.duration, tags=[tag.name for tag in bumper.tags.all()]
    )


def serialize_trailer_basic(trailer: Trailer) -> TrailerBasicSchema:
    return TrailerBasicSchema(
        id=trailer.id, title=trailer.title, year=trailer.year, content_rating=trailer.content_rating or ""
    )


def serialize_tag_basic(tag: Tag) -> TagBasicSchema:
    return TagBasicSchema(id=tag.id, name=tag.name)


def serialize_template(template: ProgrammeTemplate) -> TemplateSchema:
    items = []
    template_items = template.items.all().order_by("order")

    for item in template_items:
        item_data = TemplateItemSchema(
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
            bumper=serialize_bumper_basic(item.bumper) if item.bumper else None,
            trailer=serialize_trailer_basic(item.trailer) if item.trailer else None,
            tag=serialize_tag_basic(item.tag) if item.tag else None,
            trailer_tag=(
                TagBasicSchema(id=item.trailer_tag.id, name=item.trailer_tag.name) if item.trailer_tag else None
            ),
            credits_command=serialize_command_basic(item.credits_command) if item.credits_command else None,
        )
        items.append(item_data)

    return TemplateSchema(
        id=template.id,
        name=template.name,
        description=template.description or "",
        number_of_features=template.number_of_features,
        created_at=template.created_at.isoformat(),
        items=items,
    )


def serialize_template_summary(template: ProgrammeTemplate) -> TemplateSummarySchema:
    return TemplateSummarySchema(
        id=template.id,
        name=template.name,
        description=template.description or "",
        number_of_features=template.number_of_features,
        items_count=template.items.count(),
        item_types=list(template.items.order_by("order").values_list("item_type", flat=True)),
        created_at=template.created_at.isoformat(),
    )


@template_api.get("/list", response={200: TemplateListResponseSchema, 500: ErrorResponseSchema})
def list_templates(request: HttpRequest, filters: TemplateListFilters = Query(...)):
    per_page = min(filters.per_page, 100)
    offset = (filters.page - 1) * per_page

    templates = ProgrammeTemplate.objects.all()

    if filters.search:
        templates = templates.filter(Q(name__icontains=filters.search) | Q(description__icontains=filters.search))

    total_count = templates.count()

    paginated_templates = templates.order_by("-created_at")[offset : offset + per_page]

    return Status(
        200,
        TemplateListResponseSchema(
            message="Templates retrieved successfully",
            data=TemplateListDataSchema(
                templates=[serialize_template_summary(template) for template in paginated_templates],
                pagination=TemplatePaginationSchema(
                    page=filters.page,
                    per_page=per_page,
                    total=total_count,
                    total_pages=(total_count + per_page - 1) // per_page,
                ),
            ),
        ),
    )


@template_api.post(
    "/create",
    response={
        201: TemplateCreateResponseSchema,
        400: ErrorResponseSchema,
        404: ErrorResponseSchema,
        422: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def create_template(request: HttpRequest, data: CreateTemplateSchema):
    with transaction.atomic():
        if not data.name.strip():
            raise ValidationError("Template name is required", error_code="TEMPLATE_NAME_REQUIRED")

        template = ProgrammeTemplate.objects.create(
            name=data.name.strip(), description=data.description or "", number_of_features=data.number_of_features
        )

        for item in data.items:
            block_data = {
                "template": template,
                "item_type": item.item_type,
                "order": item.order,
                "feature_number": item.feature_number,
                "bound_to_feature": item.bound_to_feature,
                "trailer_count": item.trailer_count,
                "match_genre": item.match_genre,
                "match_certification": item.match_certification,
                "match_year": item.match_year,
                "year_delta": item.year_delta,
                "certification_feature": item.certification_feature,
                "count": item.count,
                "hold_black": item.hold_black,
            }

            if item.command_id:
                try:
                    block_data["command"] = Command.objects.get(pk=item.command_id)
                except Command.DoesNotExist:
                    raise NotFoundError(
                        f"Command {item.command_id} not found", error_code="COMMAND_NOT_FOUND"
                    ) from None

            if item.bumper_id:
                try:
                    block_data["bumper"] = Bumper.objects.get(pk=item.bumper_id)
                except Bumper.DoesNotExist:
                    raise NotFoundError(
                        f"User media item {item.bumper_id} not found", error_code="BUMPER_NOT_FOUND"
                    ) from None

            if item.trailer_id:
                try:
                    block_data["trailer"] = Trailer.objects.get(pk=item.trailer_id)
                except Trailer.DoesNotExist:
                    raise NotFoundError(
                        f"Trailer {item.trailer_id} not found", error_code="TRAILER_NOT_FOUND"
                    ) from None

            if item.tag_id:
                try:
                    block_data["tag"] = Tag.objects.get(pk=item.tag_id)
                except Tag.DoesNotExist:
                    raise NotFoundError(f"Tag {item.tag_id} not found", error_code="TAG_NOT_FOUND") from None

            if item.trailer_tag_id:
                try:
                    block_data["trailer_tag"] = TrailerTag.objects.get(pk=item.trailer_tag_id)
                except TrailerTag.DoesNotExist:
                    raise NotFoundError(
                        f"Trailer tag {item.trailer_tag_id} not found", error_code="TRAILER_TAG_NOT_FOUND"
                    ) from None

            if item.credits_command_id:
                try:
                    block_data["credits_command"] = Command.objects.get(pk=item.credits_command_id)
                except Command.DoesNotExist:
                    raise NotFoundError(
                        f"Command {item.credits_command_id} not found", error_code="CREDITS_COMMAND_NOT_FOUND"
                    ) from None

            ProgrammeTemplateItem.objects.create(**block_data)

        return Status(
            201,
            TemplateCreateResponseSchema(
                message="Template created successfully", data=TemplateDataSchema(id=template.id, name=template.name)
            ),
        )


@template_api.post(
    "/{template_id}/duplicate",
    response={201: TemplateCreateResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def duplicate_template(request: HttpRequest, template_id: int):
    try:
        original = ProgrammeTemplate.objects.get(id=template_id)
    except ProgrammeTemplate.DoesNotExist:
        raise NotFoundError("Template not found", error_code="TEMPLATE_NOT_FOUND") from None

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

    return Status(
        201,
        TemplateCreateResponseSchema(
            message="Template duplicated successfully", data=TemplateDataSchema(id=copy.id, name=copy.name)
        ),
    )


@template_api.get(
    "/{template_id}", response={200: TemplateDetailResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema}
)
def get_template_detail(request: HttpRequest, template_id: int):
    try:
        template = ProgrammeTemplate.objects.get(pk=template_id)
    except ProgrammeTemplate.DoesNotExist:
        raise NotFoundError("Template not found", error_code="TEMPLATE_NOT_FOUND") from None

    template_data = serialize_template(template)
    return Status(
        200,
        TemplateDetailResponseSchema(
            message="Template retrieved successfully",
            data=TemplateDataSchema(id=template.id, name=template.name, template=template_data),
        ),
    )


@template_api.put(
    "/{template_id}",
    response={
        200: TemplateCreateResponseSchema,
        404: ErrorResponseSchema,
        400: ErrorResponseSchema,
        422: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def update_template(request: HttpRequest, template_id: int, data: UpdateTemplateSchema):
    with transaction.atomic():
        try:
            template = ProgrammeTemplate.objects.get(pk=template_id)
        except ProgrammeTemplate.DoesNotExist:
            raise NotFoundError("Template not found", error_code="TEMPLATE_NOT_FOUND") from None

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

            for item in data.items:
                block_data = {
                    "template": template,
                    "item_type": item.item_type,
                    "order": item.order,
                    "feature_number": item.feature_number,
                    "bound_to_feature": item.bound_to_feature,
                    "trailer_count": item.trailer_count,
                    "match_genre": item.match_genre,
                    "match_certification": item.match_certification,
                    "match_year": item.match_year,
                    "year_delta": item.year_delta,
                    "certification_feature": item.certification_feature,
                    "count": item.count,
                    "hold_black": item.hold_black,
                }

                if item.command_id:
                    try:
                        block_data["command"] = Command.objects.get(pk=item.command_id)
                    except Command.DoesNotExist:
                        raise NotFoundError(
                            f"Command {item.command_id} not found", error_code="COMMAND_NOT_FOUND"
                        ) from None

                if item.bumper_id:
                    try:
                        block_data["bumper"] = Bumper.objects.get(pk=item.bumper_id)
                    except Bumper.DoesNotExist:
                        raise NotFoundError(
                            f"User media item {item.bumper_id} not found", error_code="BUMPER_NOT_FOUND"
                        ) from None

                if item.trailer_id:
                    try:
                        block_data["trailer"] = Trailer.objects.get(pk=item.trailer_id)
                    except Trailer.DoesNotExist:
                        raise NotFoundError(
                            f"Trailer {item.trailer_id} not found", error_code="TRAILER_NOT_FOUND"
                        ) from None

                if item.tag_id:
                    try:
                        block_data["tag"] = Tag.objects.get(pk=item.tag_id)
                    except Tag.DoesNotExist:
                        raise NotFoundError(f"Tag {item.tag_id} not found", error_code="TAG_NOT_FOUND") from None

                if item.trailer_tag_id:
                    try:
                        block_data["trailer_tag"] = TrailerTag.objects.get(pk=item.trailer_tag_id)
                    except TrailerTag.DoesNotExist:
                        raise NotFoundError(
                            f"Trailer tag {item.trailer_tag_id} not found", error_code="TRAILER_TAG_NOT_FOUND"
                        ) from None

                if item.credits_command_id:
                    try:
                        block_data["credits_command"] = Command.objects.get(pk=item.credits_command_id)
                    except Command.DoesNotExist:
                        raise NotFoundError(
                            f"Command {item.credits_command_id} not found", error_code="CREDITS_COMMAND_NOT_FOUND"
                        ) from None

                ProgrammeTemplateItem.objects.create(**block_data)

        return Status(
            200,
            TemplateCreateResponseSchema(
                message="Template updated successfully", data=TemplateDataSchema(id=template.id, name=template.name)
            ),
        )


@template_api.delete(
    "/{template_id}", response={200: MessageResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema}
)
def delete_template(request: HttpRequest, template_id: int):
    try:
        template = ProgrammeTemplate.objects.get(pk=template_id)
    except ProgrammeTemplate.DoesNotExist:
        raise NotFoundError("Template not found", error_code="TEMPLATE_NOT_FOUND") from None

    template_name = template.name
    template.delete()

    return Status(200, MessageResponseSchema(message=f'Template "{template_name}" deleted successfully'))
