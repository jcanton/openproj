# syntax=docker/dockerfile:1.7

FROM python:3.12-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies in their own layer: pyproject and the lock change far less often
# than src/, so editing a renderer must not re-resolve the world.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

FROM python:3.12-slim-bookworm
# ca-certificates is not optional and is the classic slim trap: without it every
# clone and push to github.com fails TLS, and libgit2 does not say why. pygit2
# bundles libgit2 and speaks HTTPS itself, so no compiler and no libgit2-dev.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates git \
 && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin openproj

WORKDIR /app
COPY --from=build /app/.venv /app/.venv
# The source tree, not the wheel: static/ is not packaged, and render.py resolves
# it relative to the source layout. OPENPROJ_STATIC says so explicitly anyway.
COPY --chown=openproj:openproj src/     /app/src/
COPY --chown=openproj:openproj static/  /app/static/
COPY --chown=openproj:openproj deploy/boot.py /app/boot.py

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    OPENPROJ_STATIC=/app/static \
    OPENPROJ_REPO=/srv/plan.git \
    PORT=8080
RUN install -d -o openproj -g openproj /srv
USER openproj:openproj
EXPOSE 8080
CMD ["python", "/app/boot.py"]
