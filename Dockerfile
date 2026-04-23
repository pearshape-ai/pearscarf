# syntax=docker/dockerfile:1

# Builder: uv-enabled image for resolving + installing deps and building the project.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY pearscarf/ ./pearscarf/
COPY experts/ ./experts/
COPY scripts/ ./scripts/
COPY README.md CHANGELOG.md ./
RUN uv sync --frozen --no-dev


# Runtime: vanilla Python slim. Copies the built venv + app code from the builder.
# No uv, no build caches, no dev tooling.
FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app /app
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    EXPERTS_DIR=/app/experts

ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]
CMD ["psc", "dev", "--poll"]
