import os

from django.conf import settings
from django.shortcuts import get_object_or_404
from ninja import File, Router, Schema, Status, UploadedFile
from pydantic import Field

from ..exceptions import ConflictError, UnprocessableEntityError, ValidationError
from ..models import Programme, ProgrammeTitleTemplate
from ..services.titlegen_service import TitleGenService
from ..utils.media_paths import usermedia_abs_path
from .media.utils import sanitize_filename

titlegen_api = Router()


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


class ImageUploadResponse(Schema):
    success: bool
    message: str
    url: str | None = None
    filename: str | None = None


@titlegen_api.get("/templates", response=list[TitleTemplateSchema], tags=["Title Generation"])
def list_title_templates(request):
    templates = ProgrammeTitleTemplate.objects.all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "template_config": t.template_config,
            "default_duration": t.default_duration,
            "created_at": t.created_at.isoformat(),
            "updated_at": t.updated_at.isoformat(),
        }
        for t in templates
    ]


@titlegen_api.get("/templates/{template_id}", response=TitleTemplateSchema, tags=["Title Generation"])
def get_title_template(request, template_id: int):
    template = get_object_or_404(ProgrammeTitleTemplate, id=template_id)
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "template_config": template.template_config,
        "default_duration": template.default_duration,
        "created_at": template.created_at.isoformat(),
        "updated_at": template.updated_at.isoformat(),
    }


@titlegen_api.get("/templates/{template_id}/preview", tags=["Title Generation"])
def render_template_thumbnail(request, template_id: int, programme_id: int | None = None):
    """Server-rendered PNG thumbnail of a template; with programme_id, against that programme's real features."""
    import io

    from django.http import HttpResponse

    template = get_object_or_404(ProgrammeTitleTemplate, id=template_id)
    programme = Programme.objects.filter(id=programme_id).first() if programme_id else None
    frame = TitleGenService.render_config_frame(template.template_config, programme=programme)
    buffer = io.BytesIO()
    frame.save(buffer, format="PNG")
    response = HttpResponse(buffer.getvalue(), content_type="image/png")
    response["Cache-Control"] = "private, max-age=86400"
    return response


@titlegen_api.post("/templates", response={200: TitleTemplateSchema, 400: MessageResponse}, tags=["Title Generation"])
def create_title_template(request, payload: TitleTemplateCreateSchema):
    if ProgrammeTitleTemplate.objects.filter(name=payload.name).exists():
        raise ConflictError(f"A template with the name '{payload.name}' already exists", error_code="DUPLICATE_NAME")

    try:
        template = ProgrammeTitleTemplate.objects.create(
            name=payload.name,
            description=payload.description,
            template_config=payload.template_config,
            default_duration=payload.default_duration,
        )

        return Status(
            200,
            {
                "id": template.id,
                "name": template.name,
                "description": template.description,
                "template_config": template.template_config,
                "default_duration": template.default_duration,
                "created_at": template.created_at.isoformat(),
                "updated_at": template.updated_at.isoformat(),
            },
        )
    except Exception as e:
        raise UnprocessableEntityError(f"Failed to create template: {str(e)}") from e


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

    try:
        if payload.name is not None:
            template.name = payload.name
        if payload.description is not None:
            template.description = payload.description
        if payload.template_config is not None:
            template.template_config = payload.template_config
        if payload.default_duration is not None:
            template.default_duration = payload.default_duration

        template.save()

        return Status(
            200,
            {
                "id": template.id,
                "name": template.name,
                "description": template.description,
                "template_config": template.template_config,
                "default_duration": template.default_duration,
                "created_at": template.created_at.isoformat(),
                "updated_at": template.updated_at.isoformat(),
            },
        )
    except Exception as e:
        raise UnprocessableEntityError(f"Failed to update template: {str(e)}") from e


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

    try:
        template_name = template.name
        template.delete()
        return Status(200, {"success": True, "message": f"Template '{template_name}' deleted successfully"})
    except Exception as e:
        raise UnprocessableEntityError(f"Failed to delete template: {str(e)}") from e


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
        service = TitleGenService(programme)
        result = service.generate_title()

        if not result["success"]:
            raise UnprocessableEntityError(
                f"Title generation failed: {result.get('error')}", error_code="GENERATION_FAILED"
            )

        return Status(
            200,
            {
                "success": True,
                "message": "Title card generated successfully",
                "file_path": result.get("file_path"),
                "duration": result.get("duration"),
            },
        )

    except UnprocessableEntityError:
        raise
    except Exception as e:
        raise UnprocessableEntityError(f"Title generation failed: {str(e)}", error_code="GENERATION_FAILED") from e


@titlegen_api.get("/programmes/{programme_id}/title-status", response=dict, tags=["Title Generation"])
def get_programme_title_status(request, programme_id: int):
    programme = get_object_or_404(Programme, id=programme_id)

    import os

    has_title_file = bool(programme.title_file and os.path.exists(usermedia_abs_path(programme.title_file)))

    return {
        "programme_id": programme.id,
        "programme_name": programme.name,
        "has_template": programme.title_template is not None,
        "template_name": programme.title_template.name if programme.title_template else None,
        "background_type": programme.title_background_type,
        "has_title_file": has_title_file,
        "title_file_path": programme.title_file if has_title_file else None,
        "duration": programme.title_duration,
        "feature_count": len(programme.get_feature_movies()),
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
    import io

    from django.http import HttpResponse

    programme = None
    if payload.programme_id:
        programme = get_object_or_404(Programme, id=payload.programme_id)

    frame = TitleGenService.render_config_frame(payload.template_config, programme)
    buffer = io.BytesIO()
    frame.save(buffer, format="PNG")
    return HttpResponse(buffer.getvalue(), content_type="image/png")


@titlegen_api.get("/images", response=list[str], tags=["Title Generation"])
def list_title_images(request):
    upload_dir = os.path.join(settings.MEDIA_ROOT, "programme_title_images")

    if not os.path.exists(upload_dir):
        return []

    images = []
    for filename in os.listdir(upload_dir):
        if filename.lower().endswith((".png", ".jpg", ".jpeg")):
            url = f"{settings.MEDIA_URL}programme_title_images/{filename}"
            images.append(url)

    return sorted(images)


@titlegen_api.post(
    "/upload-image", response={200: ImageUploadResponse, 400: ImageUploadResponse}, tags=["Title Generation"]
)
def upload_title_image(request, file: UploadedFile = File(...)):
    allowed_types = ["image/png", "image/jpeg", "image/jpg"]
    if file.content_type not in allowed_types:
        raise ValidationError(
            f"Invalid file type. Only PNG and JPEG images are allowed. Received: {file.content_type}",
            error_code="INVALID_FILE_TYPE",
        )

    upload_dir = os.path.join(settings.MEDIA_ROOT, "programme_title_images")
    os.makedirs(upload_dir, exist_ok=True)

    # Strip directory components so a crafted name can't escape the upload directory.
    filename = sanitize_filename(file.name or "image.png")
    file_path = os.path.join(upload_dir, filename)

    if os.path.exists(file_path):
        raise ConflictError(
            f"A file with the name '{filename}' already exists. Please rename your file or delete the existing one.",
            error_code="DUPLICATE_FILENAME",
        )

    try:
        with open(file_path, "wb") as f:
            for chunk in file.chunks():
                f.write(chunk)

        url = f"{settings.MEDIA_URL}programme_title_images/{filename}"

        return Status(
            200, {"success": True, "message": "Image uploaded successfully", "url": url, "filename": filename}
        )
    except Exception as e:
        raise UnprocessableEntityError(f"Failed to upload image: {str(e)}") from e
