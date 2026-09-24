import logging
from typing import Any

from ninja import Query, Router, Schema

from cinefin.api.sync import registry
from cinefin.api.sync.service import SyncManager

logger = logging.getLogger(__name__)

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


@sync_api.get("/types", tags=["Sync"])
def list_source_types(request):
    return ok({"types": registry.list_types()})


@sync_api.get("/sources", tags=["Sync"])
def list_sources(request):
    sources = SyncManager.list_sources()
    return ok({"sources": sources, "count": len(sources), "types": registry.list_types()})


@sync_api.get("/source", tags=["Sync"])
def get_the_source(request):
    """The library's ONE source, or null before one is configured."""
    source = SyncManager.the_source()
    return ok(
        {
            "source": SyncManager.serialize_source(source) if source else None,
            "types": registry.list_types(),
        }
    )


@sync_api.get("/sources/{int:source_id}", tags=["Sync"])
def get_source(request, source_id: int):
    source = SyncManager.get_source(source_id)
    return ok({"source": SyncManager.serialize_source(source)})


@sync_api.post("/sources", tags=["Sync"])
def create_source(request, payload: SourceCreateSchema):
    source = SyncManager.create_source(payload.dict(exclude_none=True))
    return ok({"source": SyncManager.serialize_source(source)})


@sync_api.patch("/sources/{int:source_id}", tags=["Sync"])
def update_source(request, source_id: int, payload: SourceUpdateSchema):
    source = SyncManager.update_source(source_id, payload.dict(exclude_unset=True))
    return ok({"source": SyncManager.serialize_source(source)})


@sync_api.delete("/sources/{int:source_id}", tags=["Sync"])
def delete_source(request, source_id: int):
    SyncManager.delete_source(source_id)
    return ok({"deleted": True})


@sync_api.post("/sources/{int:source_id}/test", tags=["Sync"])
def test_connection(request, source_id: int):
    return ok(SyncManager.test_connection(source_id))


@sync_api.post("/probe", tags=["Sync"])
def probe(request, payload: ProbeSchema):
    """Test an un-saved connection and list its libraries (for the Add/Edit form)."""
    return ok(
        SyncManager.probe(
            sync_type=payload.sync_type,
            url=payload.url,
            token=payload.token,
            source_id=payload.source_id,
        )
    )


@sync_api.post("/sources/{int:source_id}/runs", tags=["Sync"])
def start_run(request, source_id: int, payload: RunSchema):
    job = SyncManager.enqueue(
        source_id,
        operation=payload.operation,
        params=payload.params or {},
        max_attempts=payload.max_attempts,
    )
    return ok({"job": SyncManager.serialize_job(job)})


@sync_api.delete("/sources/{int:source_id}/runs/current", tags=["Sync"])
def cancel_run(request, source_id: int):
    job = SyncManager.cancel_active(source_id)
    return ok({"job": SyncManager.serialize_job(job, brief=True)})


@sync_api.get("/sources/{int:source_id}/runs", tags=["Sync"])
def list_runs(request, source_id: int, limit: int = Query(25, ge=1, le=200)):
    jobs = SyncManager.list_jobs(source_id=source_id, limit=limit)
    return ok({"runs": [SyncManager.serialize_job(j) for j in jobs]})


@sync_api.get("/jobs", tags=["Sync"])
def list_jobs(request, limit: int = Query(50, ge=1, le=200), active_only: bool = False):
    jobs = SyncManager.list_jobs(limit=limit, active_only=active_only)
    return ok({"jobs": [SyncManager.serialize_job(j, brief=True) for j in jobs]})


@sync_api.get("/jobs/{int:job_id}", tags=["Sync"])
def get_job(request, job_id: int, include_log: bool = True):
    job = SyncManager.get_job(job_id)
    return ok({"job": SyncManager.serialize_job(job, include_log=include_log)})
