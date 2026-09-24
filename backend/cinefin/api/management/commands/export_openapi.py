"""Export the Django Ninja OpenAPI schema as JSON for the SPA's generated client."""

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

# Relative `path` is resolved against REPO_ROOT so output lands in sibling frontend/.
DEFAULT_PATH = "frontend/src/lib/api/openapi.json"


class Command(BaseCommand):
    help = (
        "Write the Ninja OpenAPI schema (paths prefixed with /api/v2) as JSON. "
        f"Default output: {DEFAULT_PATH} — the input for the SPA's generated API client."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "path",
            nargs="?",
            default=DEFAULT_PATH,
            help=f"Output file path (default {DEFAULT_PATH})",
        )

    def handle(self, *args, **options):
        from cinefin.api.ninja_api import api

        prefix = "/api/v2"
        schema = api.get_openapi_schema(path_prefix=prefix)
        # Ninja quirk: routers nested via add_router("/", …) emit paths without a
        # leading slash ("/api/v2programmes/list"); normalise so clients hit real endpoints.
        schema["paths"] = {
            f"{prefix}/{rest.lstrip('/')}": ops
            for path, ops in schema["paths"].items()
            for rest in [path[len(prefix) :] if path.startswith(prefix) else path]
        }
        # Ninja derives operationIds from module path, so a function on multiple
        # methods repeats its id (invalid OpenAPI); suffix repeats with the method.
        seen: set[str] = set()
        for ops in schema["paths"].values():
            for method, op in ops.items():
                op_id = op.get("operationId")
                if not op_id:
                    continue
                if op_id in seen:
                    op_id = f"{op_id}_{method}"
                    op["operationId"] = op_id
                seen.add(op_id)
        out = Path(options["path"])
        if not out.is_absolute():
            out = Path(settings.REPO_ROOT) / out
        out.parent.mkdir(parents=True, exist_ok=True)
        # Stable formatting (indent + sorted keys) so regeneration diffs stay minimal.
        out.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
        self.stdout.write(self.style.SUCCESS(f"Wrote OpenAPI schema ({len(schema.get('paths', {}))} paths) to {out}"))
