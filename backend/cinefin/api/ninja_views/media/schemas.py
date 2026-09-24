from ninja import Field, Schema


class TagSchema(Schema):
    id: int = Field(description="Tag unique identifier")
    name: str = Field(description="Tag name")
    color: str | None = Field(None, description="Optional badge colour as #RRGGBB (null = neutral)")
    count: int | None = Field(None, description="Number of media items carrying this tag, when computed")


class FileInfoSchema(Schema):
    size: int | None = Field(None, description="File size in bytes")
    mime_type: str | None = Field(None, description="MIME type of the file")
    exists: bool = Field(..., description="Whether the file exists on disk")


class MediaItemSchema(Schema):
    id: int = Field(description="Media unique identifier")
    title: str = Field(description="Media title")
    duration: float | None = Field(None, description="Duration in seconds")
    file_path: str = Field(description="Path to media file")
    file_url: str | None = Field(None, description="URL to access the file")
    screenshot_url: str | None = Field(None, description="URL to screenshot/thumbnail")
    file_info: FileInfoSchema = Field(description="File system information")
    tags: list[TagSchema] = Field(description="Associated tags")
    upload_date: str | None = Field(None, description="Upload timestamp in ISO format")
    audio_format: str | None = Field(None, description="Audio format this intro announces, if any")


class MediaPaginationSchema(Schema):
    page: int = Field(description="Current page number")
    per_page: int = Field(description="Items per page")
    total: int = Field(description="Total number of items")
    total_pages: int = Field(description="Total number of pages")
    has_previous: bool = Field(description="Whether there is a previous page")
    has_next: bool = Field(description="Whether there is a next page")


class MediaFiltersSchema(Schema):
    tags: list[str] = Field(description="Available tag names for filtering")
    tag_facets: list[TagSchema] = Field(
        default_factory=list,
        description="Available tags with item counts and colours, for the multi-select filter",
    )


class MediaListDataSchema(Schema):
    media: list[MediaItemSchema] = Field(description="List of media items")
    pagination: MediaPaginationSchema = Field(description="Pagination information")
    filters: MediaFiltersSchema = Field(description="Available filters")


class MediaListResponseSchema(Schema):
    success: bool = Field(description="Request success status")
    message: str = Field(description="Response message")
    data: MediaListDataSchema = Field(description="Media list data")


class CreateMediaSchema(Schema):
    title: str = Field(description="Media title")
    file_path: str = Field(description="Path to existing media file")
    tag_names: list[str] | None = Field(default=[], description="List of tag names to associate")


class UpdateMediaSchema(Schema):
    title: str | None = Field(None, description="Updated media title")
    tag_names: list[str] | None = Field(None, description="Updated list of tag names")
    audio_format: str | None = Field(None, description="Audio format this intro announces ('' to clear)")


class MediaCreateDataSchema(Schema):
    id: int = Field(description="Created media ID")
    title: str = Field(description="Media title")
    duration: float | None = Field(None, description="Media duration in seconds")
    file_path: str = Field(description="Path to media file")
    file_url: str | None = Field(None, description="URL to access the file")
    screenshot_url: str | None = Field(None, description="URL to screenshot/thumbnail")
    screenshot_generated: bool = Field(description="Whether screenshot was generated")
    tags: list[TagSchema] = Field(description="Associated tags")
    upload_date: str | None = Field(None, description="Upload timestamp")


class MediaCreateResponseSchema(Schema):
    success: bool = Field(description="Request success status")
    message: str = Field(description="Response message")
    data: MediaCreateDataSchema = Field(description="Created media data")


class MediaDetailDataSchema(Schema):
    id: int = Field(description="Media ID")
    title: str = Field(description="Media title")
    duration: float | None = Field(None, description="Duration in seconds")
    file_path: str = Field(description="Path to media file")
    file_url: str | None = Field(None, description="URL to access the file")
    screenshot_url: str | None = Field(None, description="URL to screenshot/thumbnail")
    file_info: FileInfoSchema = Field(description="File system information")
    tags: list[TagSchema] = Field(description="Associated tags")
    upload_date: str | None = Field(None, description="Upload timestamp in ISO format")
    audio_format: str | None = Field(None, description="Audio format this intro announces, if any")


class MediaDetailSchema(Schema):
    success: bool = Field(description="Request success status")
    message: str = Field(description="Response message")
    data: MediaDetailDataSchema = Field(description="Media details")


class TagListDataSchema(Schema):
    tags: list[TagSchema] = Field(description="List of tags")
    pagination: MediaPaginationSchema = Field(description="Pagination information")


class TagListResponseSchema(Schema):
    success: bool = Field(description="Request success status")
    message: str = Field(description="Response message")
    data: TagListDataSchema = Field(description="Tag list data")


class TagCreateSchema(Schema):
    name: str = Field(description="Tag name")
    color: str | None = Field(None, description="Optional badge colour as #RRGGBB")


class TagUpdateSchema(Schema):
    name: str | None = Field(None, description="New tag name")
    color: str | None = Field(None, description="New badge colour as #RRGGBB, or '' to clear")


class TagResponseSchema(Schema):
    success: bool = Field(description="Request success status")
    message: str = Field(description="Response message")
    data: TagSchema = Field(description="The affected tag")


class BulkTagSchema(Schema):
    ids: list[int] = Field(description="Media item IDs to act on")
    tag: str = Field(description="Tag name to add or remove")
    action: str = Field("add", description="'add' or 'remove'")


class BulkTagDataSchema(Schema):
    updated: int = Field(description="Number of media items changed")
    missing: list[int] = Field(description="Requested IDs that were not found")
    action: str = Field(description="Action applied ('add' or 'remove')")
    tag: TagSchema | None = Field(None, description="The tag added/removed (with fresh count)")


class BulkTagResponseSchema(Schema):
    success: bool = Field(description="Request success status")
    message: str = Field(description="Response message")
    data: BulkTagDataSchema = Field(description="Bulk-tag result")


class MediaListFilters(Schema):
    search: str | None = Field(None, description="Search term for title")
    tags: str | None = Field(
        None,
        description="Comma-separated tag names; an item must carry ALL of them (AND) to match",
    )
    page: int = Field(1, description="Page number")
    per_page: int = Field(20, description="Items per page")
    sort: str | None = Field(None, description="Sort field: title | duration | file_size | upload_date")
    order: str | None = Field("desc", description="Sort direction: asc | desc")


class TagListFilters(Schema):
    search: str | None = Field(None, description="Search term for tag name")
    page: int = Field(1, description="Page number")
    per_page: int = Field(20, description="Items per page")


class YouTubeDownloadSchema(Schema):
    url: str = Field(description="YouTube video URL")
    title: str | None = Field(None, description="Custom title for downloaded video")
    tag_names: list[str] | None = Field(default=[], description="Tags to assign to downloaded video")


class YouTubeTaskDataSchema(Schema):
    task_id: str = Field(description="Unique task identifier for tracking progress")


class YouTubeTaskResponseSchema(Schema):
    success: bool = Field(description="Request success status")
    message: str = Field(description="Response message")
    data: YouTubeTaskDataSchema = Field(description="Task information")


class YouTubeProgressDataSchema(Schema):
    task_id: str = Field(description="Task identifier")
    status: str = Field(description="Download status (downloading, completed, failed)")
    progress: float | None = Field(None, description="Download progress percentage (0-100)")
    filename: str | None = Field(None, description="Downloaded filename")
    error: str | None = Field(None, description="Error message if failed")
    media_id: int | None = Field(None, description="Created media id (when completed)")


class YouTubeProgressSchema(Schema):
    success: bool = Field(description="Request success status")
    message: str = Field(description="Response message")
    data: YouTubeProgressDataSchema = Field(description="Progress information")
