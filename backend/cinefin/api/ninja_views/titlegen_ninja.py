"""Title-card API — title templates, previews and programme title generation."""

import io
import os

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from ninja import Router, Schema
from pydantic import Field

from ..exceptions import ConflictError, UnprocessableEntityError, ValidationError
from ..models import Programme, ProgrammeTitleTemplate
from ..services.titlegen_service import TitleGenService
from ..utils.media_paths import usermedia_abs_path

titlegen_api = Router()


def _png(frame) -> HttpResponse:
    buffer = io.BytesIO()
    frame.save(buffer, format="PNG")
    return HttpResponse(buffer.getvalue(), content_type="image/png")


def _template_out(template: ProgrammeTitleTemplate) -> dict:
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "template_config": template.template_config,
        "default_duration": template.default_duration,
        "created_at": template.created_at.isoformat(),
        "updated_at": template.updated_at.isoformat(),
    }


class TitleTemplateSchema(Schema):
    id: int
    name: str
    description: str
    template_config: dict
    default_duration: int
    created_at: str
    updated_at: str


class TitleTemplateCreateSchema(Schema):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field("", max_length=1000)
    template_config: dict = Field(..., description="JSON configuration for title layout")
    default_duration: int = Field(10, description="Default duration in seconds", ge=1, le=300)


class TitleTemplateUpdateSchema(Schema):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    template_config: dict | None = Field(None)
    default_duration: int | None = Field(None, ge=1, le=300)


class GenerateTitleRequest(Schema):
    regenerate: bool = Field(False, description="Force regeneration even if title already exists")


class GenerateTitleResponse(Schema):
    success: bool
    message: str
    file_path: str | None = None
    duration: int | None = None
    error: str | None = None


class MessageResponse(Schema):
    success: bool
    message: str


@titlegen_api.get("/templates", response=list[TitleTemplateSchema], tags=["Title Generation"])
def list_title_templates(request):
    return [_template_out(t) for t in ProgrammeTitleTemplate.objects.all()]


@titlegen_api.get("/templates/{template_id}", response=TitleTemplateSchema, tags=["Title Generation"])
def get_title_template(request, template_id: int):
    return _template_out(get_object_or_404(ProgrammeTitleTemplate, id=template_id))


@titlegen_api.get("/templates/{template_id}/preview", tags=["Title Generation"])
def render_template_thumbnail(request, template_id: int, programme_id: int | None = None):
    """Server-rendered PNG thumbnail of a template; with programme_id, against that programme's real features."""
    template = get_object_or_404(ProgrammeTitleTemplate, id=template_id)
    programme = Programme.objects.filter(id=programme_id).first() if programme_id else None
    response = _png(TitleGenService.render_config_frame(template.template_config, programme=programme))
    response["Cache-Control"] = "private, max-age=86400"
    return response


@titlegen_api.post("/templates", response={200: TitleTemplateSchema, 400: MessageResponse}, tags=["Title Generation"])
def create_title_template(request, payload: TitleTemplateCreateSchema):
    if ProgrammeTitleTemplate.objects.filter(name=payload.name).exists():
        raise ConflictError(f"A template with the name '{payload.name}' already exists", error_code="DUPLICATE_NAME")

    return _template_out(ProgrammeTitleTemplate.objects.create(**payload.dict()))


@titlegen_api.put(
    "/templates/{template_id}",
    response={200: TitleTemplateSchema, 400: MessageResponse, 404: MessageResponse},
    tags=["Title Generation"],
)
def update_title_template(request, template_id: int, payload: TitleTemplateUpdateSchema):
    template = get_object_or_404(ProgrammeTitleTemplate, id=template_id)

    if payload.name and payload.name != template.name:
        if ProgrammeTitleTemplate.objects.filter(name=payload.name).exists():
            raise ConflictError(
                f"A template with the name '{payload.name}' already exists", error_code="DUPLICATE_NAME"
            )

    for key, value in payload.dict(exclude_none=True).items():
        setattr(template, key, value)
    template.save()
    return _template_out(template)


@titlegen_api.delete(
    "/templates/{template_id}", response={200: MessageResponse, 400: MessageResponse}, tags=["Title Generation"]
)
def delete_title_template(request, template_id: int):
    template = get_object_or_404(ProgrammeTitleTemplate, id=template_id)

    if template.programmes.exists():
        raise ConflictError(
            f"Cannot delete template '{template.name}' as it is in use by {template.programmes.count()} programme(s)",
            error_code="TEMPLATE_IN_USE",
        )

    template.delete()
    return {"success": True, "message": f"Template '{template.name}' deleted successfully"}


@titlegen_api.post(
    "/programmes/{programme_id}/generate",
    response={200: GenerateTitleResponse, 400: GenerateTitleResponse},
    tags=["Title Generation"],
)
def generate_programme_title(request, programme_id: int, payload: GenerateTitleRequest):
    programme = get_object_or_404(Programme, id=programme_id)

    if not programme.title_template:
        raise ValidationError("Programme has no title template configured", error_code="NO_TEMPLATE")

    if programme.title_file and not payload.regenerate and os.path.exists(usermedia_abs_path(programme.title_file)):
        raise ConflictError(
            "Title already generated. Use regenerate=true to force regeneration.",
            error_code="ALREADY_EXISTS",
            details={"file_path": programme.title_file},
        )

    try:
        result = TitleGenService(programme).generate_title()
    except Exception as e:
        raise UnprocessableEntityError(f"Title generation failed: {str(e)}", error_code="GENERATION_FAILED") from e
    if not result["success"]:
        raise UnprocessableEntityError(
            f"Title generation failed: {result.get('error')}", error_code="GENERATION_FAILED"
        )
    return {
        "success": True,
        "message": "Title card generated successfully",
        "file_path": result.get("file_path"),
        "duration": result.get("duration"),
    }


class FontSchema(Schema):
    name: str
    bundled: bool = Field(..., description="Shipped with the app — the editor previews the exact same file")


@titlegen_api.get("/fonts", response=list[FontSchema], tags=["Title Generation"])
def list_fonts(request):
    return TitleGenService.available_fonts()


class TitlePreviewRequest(Schema):
    template_config: dict = Field(..., description="The template configuration to render")
    programme_id: int | None = Field(None, description="Render with this programme's real data instead of placeholders")


@titlegen_api.post("/preview", tags=["Title Generation"])
def render_title_preview(request, payload: TitlePreviewRequest):
    programme = get_object_or_404(Programme, id=payload.programme_id) if payload.programme_id else None
    return _png(TitleGenService.render_config_frame(payload.template_config, programme))
