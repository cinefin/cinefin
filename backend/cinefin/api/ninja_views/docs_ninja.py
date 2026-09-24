"""
API Documentation using Django Ninja - Endpoints for API documentation
"""

import logging
from typing import Any

from django.http import HttpRequest
from django.shortcuts import redirect
from ninja import Field, Router, Schema

from cinefin.api.schemas.base import SuccessResponseSchema

logger = logging.getLogger(__name__)


# Schema definitions
class APISummaryData(Schema):
    """API documentation summary data."""

    title: str = Field(description="API title")
    version: str = Field(description="API version")
    description: str = Field(description="API description")
    ninja_docs_url: str = Field(description="URL to interactive Ninja documentation")
    ninja_openapi_url: str = Field(description="URL to OpenAPI specification")
    endpoints_summary: dict[str, Any] = Field(description="Summary of available endpoints")


class APISummaryResponseSchema(SuccessResponseSchema):
    """Response schema for API documentation summary."""

    data: APISummaryData


# Create the API router
docs_api = Router()


@docs_api.get("/", response=APISummaryResponseSchema)
def api_documentation_summary(request: HttpRequest):
    """
    Get API documentation summary with links to auto-generated docs.

    Returns:
        200: API documentation summary with endpoint information
    """
    base_url = request.build_absolute_uri("/api/v2/")

    summary_data = APISummaryData(
        title="Cinefin V2 API Documentation",
        version="2.0",
        description="Modern self-hosted home cinema automation API built with Django Ninja",
        ninja_docs_url=f"{base_url}ninja-docs/",
        ninja_openapi_url=f"{base_url}ninja-openapi.json",
        endpoints_summary={
            "programmes": {
                "description": "Cinema programme management and playback",
                "endpoint_count": 11,
                "base_path": "/programmes",
            },
            "templates": {
                "description": "Programme template creation and management",
                "endpoint_count": 6,
                "base_path": "/templates",
            },
            "schedules": {
                "description": "Programme scheduling and automation",
                "endpoint_count": 5,
                "base_path": "/schedules",
            },
            "sync": {
                "description": "Media server synchronization (Plex, etc.)",
                "endpoint_count": 10,
                "base_path": "/sync",
            },
            "media": {
                "description": "Media file management (bumpers, adverts)",
                "endpoint_count": 8,
                "base_path": "/media",
            },
            "movies": {
                "description": "Movie library browsing and streaming",
                "endpoint_count": 7,
                "base_path": "/movies",
            },
            "trailers": {
                "description": "Movie trailer management and downloading",
                "endpoint_count": 9,
                "base_path": "/trailers",
            },
            "tickets": {
                "description": "Thermal ticket printing and configuration",
                "endpoint_count": 6,
                "base_path": "/tickets",
            },
            "playout": {
                "description": "MPV media player control and programme execution",
                "endpoint_count": 13,
                "base_path": "/playout",
            },
            "mpv": {
                "description": "Direct MPV player control (volume, seek, etc.)",
                "endpoint_count": 9,
                "base_path": "/mpv",
            },
            "commands": {
                "description": "System command management and execution",
                "endpoint_count": 7,
                "base_path": "/commands",
            },
            "settings": {
                "description": "Cinema configuration and system settings",
                "endpoint_count": 4,
                "base_path": "/settings",
            },
        },
    )

    return APISummaryResponseSchema(message="API documentation retrieved successfully", data=summary_data)


@docs_api.get("/interactive")
def redirect_to_ninja_docs(request: HttpRequest):
    """
    Redirect to the interactive Django Ninja documentation.

    Returns:
        302: Redirect to interactive documentation
    """
    return redirect("/api/v2/ninja-docs/")


@docs_api.get("/openapi.json")
def redirect_to_openapi_spec(request: HttpRequest):
    """
    Redirect to the OpenAPI specification JSON.

    Returns:
        302: Redirect to OpenAPI specification
    """
    return redirect("/api/v2/ninja-openapi.json")
