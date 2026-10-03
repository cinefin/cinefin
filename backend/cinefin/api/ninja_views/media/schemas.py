from ninja import Field, Schema


class TagSchema(Schema):
    id: int
    name: str
    color: str | None = Field(None, description="Optional badge colour as #RRGGBB (null = neutral)")
    count: int | None = Field(None, description="Number of media items carrying this tag, when computed")


class FileInfoSchema(Schema):
    size: int | None = Field(None, description="Bytes")
    mime_type: str | None = None
    exists: bool = Field(..., description="Whether the file exists on disk")


class MediaItemSchema(Schema):
    id: int
    title: str
    duration: float | None = Field(None, description="Seconds")
    file_path: str
    file_url: str | None = None
    screenshot_url: str | None = None
    file_info: FileInfoSchema
    tags: list[TagSchema]
    upload_date: str | None = Field(None, description="ISO timestamp")
    audio_format: str | None = Field(None, description="Audio format this intro announces, if any")
    hold_point: float | None = Field(
        None, description="As the ident: where standby freezes, in seconds (null = last frame)"
    )


class MediaPaginationSchema(Schema):
    page: int
    per_page: int
    total: int
    total_pages: int
    has_previous: bool
    has_next: bool


class MediaFiltersSchema(Schema):
    tags: list[str] = Field(description="Available tag names for filtering")
    tag_facets: list[TagSchema] = Field(
        default_factory=list,
        description="Available tags with item counts and colours, for the multi-select filter",
    )


class MediaListDataSchema(Schema):
    media: list[MediaItemSchema]
    pagination: MediaPaginationSchema
    filters: MediaFiltersSchema


class MediaListResponseSchema(Schema):
    success: bool
    message: str
    data: MediaListDataSchema


class CreateMediaSchema(Schema):
    title: str
    file_path: str = Field(description="Path to an existing media file")
    tag_names: list[str] | None = []


class UpdateMediaSchema(Schema):
    title: str | None = None
    tag_names: list[str] | None = None
    audio_format: str | None = Field(None, description="Audio format this intro announces ('' to clear)")
    hold_point: float | None = Field(
        None, ge=0, description="As the ident: where standby freezes, in seconds; send null for its last frame"
    )


class MediaCreateDataSchema(Schema):
    id: int
    title: str
    duration: float | None = Field(None, description="Seconds")
    file_path: str
    file_url: str | None = None
    screenshot_url: str | None = None
    screenshot_generated: bool
    tags: list[TagSchema]
    upload_date: str | None = None


class MediaCreateResponseSchema(Schema):
    success: bool
    message: str
    data: MediaCreateDataSchema


class MediaDetailDataSchema(MediaItemSchema):
    pass


class MediaDetailSchema(Schema):
    success: bool
    message: str
    data: MediaDetailDataSchema


class TagListDataSchema(Schema):
    tags: list[TagSchema]
    pagination: MediaPaginationSchema


class TagListResponseSchema(Schema):
    success: bool
    message: str
    data: TagListDataSchema


class TagCreateSchema(Schema):
    name: str
    color: str | None = Field(None, description="Optional badge colour as #RRGGBB")


class TagUpdateSchema(Schema):
    name: str | None = None
    color: str | None = Field(None, description="New badge colour as #RRGGBB, or '' to clear")


class TagResponseSchema(Schema):
    success: bool
    message: str
    data: TagSchema


class BulkTagSchema(Schema):
    ids: list[int]
    tag: str = Field(description="Tag name to add or remove")
    action: str = Field("add", description="'add' or 'remove'")


class BulkTagDataSchema(Schema):
    updated: int
    missing: list[int] = Field(description="Requested IDs that were not found")
    action: str
    tag: TagSchema | None = Field(None, description="The tag added/removed (with fresh count)")


class BulkTagResponseSchema(Schema):
    success: bool
    message: str
    data: BulkTagDataSchema


class MediaListFilters(Schema):
    search: str | None = Field(None, description="Search term for title")
    tags: str | None = Field(None, description="Comma-separated tag names; an item carrying any of them matches")
    page: int = 1
    per_page: int = 20
    sort: str | None = Field(None, description="title | duration | file_size | upload_date")
    order: str | None = Field("desc", description="asc | desc")


class TagListFilters(Schema):
    search: str | None = Field(None, description="Search term for tag name")
    page: int = 1
    per_page: int = 20


class YouTubeDownloadSchema(Schema):
    url: str
    title: str | None = None
    tag_names: list[str] | None = []


class YouTubeTaskDataSchema(Schema):
    task_id: str


class YouTubeTaskResponseSchema(Schema):
    success: bool
    message: str
    data: YouTubeTaskDataSchema


class YouTubeProgressDataSchema(Schema):
    task_id: str
    status: str = Field(description="downloading, completed or failed")
    progress: float | None = Field(None, description="Percent (0-100)")
    filename: str | None = None
    error: str | None = None
    media_id: int | None = Field(None, description="Created media id (when completed)")


class YouTubeProgressSchema(Schema):
    success: bool
    message: str
    data: YouTubeProgressDataSchema
