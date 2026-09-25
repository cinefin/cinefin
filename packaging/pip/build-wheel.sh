#!/usr/bin/env bash
#
# Build the Cinefin pip/pipx wheel: the `cinefin` server as a self-contained
# wheel with the SPA build and collected static bundled in. Users then:
#
#   pipx install ./cinefin3-<version>-py3-none-any.whl
#   cinefin            # migrate + serve on 0.0.0.0:8000
#
# ffmpeg is an optional system dependency (certification/title cards need it);
# it is NOT bundled. Run from anywhere — paths resolve to the repo.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
backend="$repo/backend"
frontend="$repo/frontend"

echo "==> Building the SPA"
(cd "$frontend" && npm ci && npm run build)

echo "==> Bundling the SPA into the package (cinefin/spa)"
rm -rf "$backend/cinefin/spa"
cp -r "$frontend/build" "$backend/cinefin/spa"

echo "==> Installing backend deps + collecting static"
(cd "$backend" && poetry install --only main --no-root)
(cd "$backend" && poetry run python manage.py collectstatic --no-input --clear)

echo "==> Building the wheel"
(cd "$backend" && poetry build --format wheel)

echo "==> Done. Wheel(s):"
ls -1 "$backend/dist/"*.whl
