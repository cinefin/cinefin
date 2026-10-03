from typing import Any

from ninja import Query, Router, Schema

from cinefin.api.sync import registry
from cinefin.api.sync.service import SyncManager

sync_api = Router()


def ok(data: Any = None) -> dict[str, Any]:
    return {"success": True, "data": data}


class SourceCreateSchema(Schema):
    name: str
    sync_type: str
    url: str | None = None
    token: str | None = None
    libraries: str | None = None
    enabled: bool = True
    extra_config: dict[str, Any] | None = None
    path_mappings: list[dict[str, str]] | None = None


class SourceUpdateSchema(Schema):
    name: str | None = None
    url: str | None = None
    token: str | None = None
    libraries: str | None = None
    enabled: bool | None = None
    extra_config: dict[str, Any] | None = None
    path_mappings: list[dict[str, str]] | None = None


class ProbeSchema(Schema):
    sync_type: str
    url: str | None = None
    token: str | None = None
    source_id: int | None = None


class RunSchema(Schema):
    operation: str | None = None
    params: dict[str, Any] | None = None
    max_attempts: int = 1


@sync_api.get("/sources")
def list_sources(request):
    sources = SyncManager.list_sources()
    return ok({"sources": sources, "count": len(sources), "types": registry.list_types()})


@sync_api.get("/source")
def get_the_source(request):
    """The library's ONE source, or null before one is configured."""
    source = SyncManager.the_source()
    return ok({"source": SyncManager.serialize_source(source) if source else None, "types": registry.list_types()})


@sync_api.post("/sources")
def create_source(request, payload: SourceCreateSchema):
    source = SyncManager.create_source(payload.dict(exclude_none=True))
    return ok({"source": SyncManager.serialize_source(source)})


@sync_api.patch("/sources/{int:source_id}")
def update_source(request, source_id: int, payload: SourceUpdateSchema):
    source = SyncManager.update_source(source_id, payload.dict(exclude_unset=True))
    return ok({"source": SyncManager.serialize_source(source)})


@sync_api.delete("/sources/{int:source_id}")
def delete_source(request, source_id: int, delete_movies: bool = False):
    movies_deleted = SyncManager.delete_source(source_id, delete_movies=delete_movies)
    return ok({"deleted": True, "movies_deleted": movies_deleted})


@sync_api.post("/sources/{int:source_id}/test")
def test_connection(request, source_id: int):
    return ok(SyncManager.test_connection(source_id))


@sync_api.post("/probe")
def probe(request, payload: ProbeSchema):
    """Test an un-saved connection and list its libraries (for the Add/Edit form)."""
    return ok(SyncManager.probe(**payload.dict()))


@sync_api.post("/sources/{int:source_id}/runs")
def start_run(request, source_id: int, payload: RunSchema):
    job = SyncManager.enqueue(
        source_id, operation=payload.operation, params=payload.params or {}, max_attempts=payload.max_attempts
    )
    return ok({"job": SyncManager.serialize_job(job)})


@sync_api.delete("/sources/{int:source_id}/runs/current")
def cancel_run(request, source_id: int):
    job = SyncManager.cancel_active(source_id)
    return ok({"job": SyncManager.serialize_job(job, brief=True)})


@sync_api.get("/jobs")
def list_jobs(request, limit: int = Query(50, ge=1, le=200), active_only: bool = False):
    jobs = SyncManager.list_jobs(limit=limit, active_only=active_only)
    return ok({"jobs": [SyncManager.serialize_job(j, brief=True) for j in jobs]})
