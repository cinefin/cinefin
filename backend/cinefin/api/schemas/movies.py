from ninja import Field, Schema


class MovieInfoSchema(Schema):
    id: int
    title: str
    year: int | None = None
    certification: str | None = None
    runtime: float | None = Field(None, description="Minutes")
    thumbnail_url: str | None = None
