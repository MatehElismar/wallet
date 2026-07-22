FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock README.md .
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini .
COPY README.md .
RUN uv sync --frozen --no-dev

FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV PATH="/app/.venv/bin:$PATH"
COPY --from=builder /app /app
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
WORKDIR /app
EXPOSE 8000
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["uvicorn", "wallet_v2.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
