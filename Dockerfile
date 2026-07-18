FROM ghcr.io/astral-sh/uv:0.11.29 AS uv
FROM python:3.14.6-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    DUNGEON_WORKSPACE_DIR=/workspace

RUN groupadd --system app && useradd --system --gid app --create-home app \
  && mkdir -p /app /workspace \
  && chown -R app:app /app /workspace

COPY --from=uv /uv /uvx /bin/
WORKDIR /app
COPY --chown=app:app pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY --chown=app:app src ./src
RUN uv sync --locked --no-dev

USER app
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"]

CMD ["/app/.venv/bin/uvicorn", "dungeon_agent.api.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
