# Cinefin — web app image.
# Runs the Django app under gunicorn; the schedule runner and sync engine run
# as background threads inside it.
# NOTE: actual MPV playout, the thermal printer and projector/lights are host
# hardware and live OUTSIDE this container — see docs/DOCKER.md.

# ---- SPA build stage ---------------------------------------------------------
# The SvelteKit SPA (frontend/) — THE UI, served by Django at /app/ from the
# static build in frontend/build (gitignored — built here, not committed).
FROM node:22-slim AS spa
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/ ./
RUN npm run build

# ---- App image ----------------------------------------------------------------
FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1 \
    DJANGO_SETTINGS_MODULE=cinefin.settings_docker
# The auto-generated SECRET_KEY persists at userdata/.secret_key (with the db and
# media, in the one mounted volume), so a backup/restore keeps sessions valid.
# Set SECRET_KEY to pin it explicitly (recommended).

# System dependencies:
#   ffmpeg          - media screenshots + moviepy (certification cards)
#   libmediainfo0v5 - pymediainfo (reads media duration)
#   libusb-1.0-0    - escpos (only used for USB thermal printers)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libmediainfo0v5 \
        libusb-1.0-0 \
        curl \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN pip install poetry

# The container mirrors the repo layout: the Python project lives in
# /app/backend (the `cinefin` package, manage.py) and the SPA build sits at
# the sibling /app/frontend/build — so settings.py's BASE_DIR (=/app/backend)
# and REPO_ROOT (=/app) resolve exactly as they do in a dev checkout. All
# runtime data lives in one dir, /app/userdata (a volume under REPO_ROOT).
WORKDIR /app/backend

# Install Python deps first for better layer caching. All dependencies come
# from PyPI — certificate-rating lookups (BBFC/MPAA) are built in and query
# the classification bodies' public websites directly.
COPY backend/pyproject.toml backend/poetry.lock ./
RUN poetry install --only main --no-root

# Application code, the contrib command-provider plugins (loaded from
# REPO_ROOT/contrib/plugins), the container entrypoint (repo-root docker/),
# then the compiled SPA on top at the sibling /app/frontend/build.
COPY backend/ ./
COPY contrib/ /app/contrib/
COPY docker/entrypoint.sh /app/docker/entrypoint.sh
COPY --from=spa /app/frontend/build/ /app/frontend/build/

# Version stamped in at build time (CI passes `git describe`). Baked into env
# vars so the running container reports the right version without git history.
ARG CINEFIN_VERSION=dev
ARG CINEFIN_COMMIT=unknown
ENV CINEFIN_VERSION=${CINEFIN_VERSION} \
    CINEFIN_COMMIT=${CINEFIN_COMMIT}
LABEL org.opencontainers.image.title="Cinefin" \
      org.opencontainers.image.version="${CINEFIN_VERSION}" \
      org.opencontainers.image.revision="${CINEFIN_COMMIT}" \
      org.opencontainers.image.source="https://github.com/cinefin-dev/cinefin"

# Collect static files for WhiteNoise (baked into the image, not a volume).
RUN python manage.py collectstatic --no-input

RUN chmod +x /app/docker/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
# uvicorn (ASGI) so the real-time WebSocket works. ONE process only — the MPV
# service is a per-process singleton and the WebSocket's in-process event bus
# must reach every client, so never add --workers.
CMD ["uvicorn", "cinefin.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
