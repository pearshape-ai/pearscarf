# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY pearscarf/ ./pearscarf/
COPY experts/ ./experts/
COPY scripts/ ./scripts/
COPY README.md CHANGELOG.md ./
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    EXPERTS_DIR=/app/experts

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["psc", "discord", "--poll"]
