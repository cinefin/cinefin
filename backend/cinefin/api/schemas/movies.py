from ninja import Field, Schema


class MovieInfoSchema(Schema):
    id: int = Field(..., description="Movie ID")
    title: str = Field(..., description="Movie title")
    year: int | None = Field(None, description="Movie release year")
    certification: str | None = Field(None, description="Movie certification")
    runtime: float | None = Field(None, description="Movie runtime in minutes")
    thumbnail_url: str | None = Field(None, description="Movie poster/thumbnail URL")
