#!/usr/bin/env bash
# Manage the isolated pearscarf test stack — postgres + neo4j + qdrant on
# alt host ports under docker compose project name "pearscarf-test".
#
# Usage:
#   scripts/test-stack.sh up     — start the stack (idempotent)
#   scripts/test-stack.sh reset  — stop, wipe state, restart
#   scripts/test-stack.sh down   — stop and wipe state
#   scripts/test-stack.sh ps     — show stack status
#
# Requires env/.test.env. Copy env/.test.env.example to env/.test.env first.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="env/.test.env"
PROJECT="pearscarf-test"
SERVICES=(postgres neo4j qdrant)

if [ ! -f "$ENV_FILE" ]; then
  echo "test-stack: $ENV_FILE missing — copy env/.test.env.example to env/.test.env first" >&2
  exit 1
fi

# Load PG_DATA_DIR / NEO4J_DATA_DIR / QDRANT_DATA_DIR so we can wipe them on down/reset.
# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a

compose() {
  docker compose --env-file "$ENV_FILE" -p "$PROJECT" "$@"
}

wipe_data() {
  for dir in "${PG_DATA_DIR:-}" "${NEO4J_DATA_DIR:-}" "${QDRANT_DATA_DIR:-}"; do
    if [ -n "$dir" ] && [ -d "$dir" ]; then
      rm -rf "$dir"
    fi
  done
}

wait_ready() {
  # `docker compose up -d` returns once containers start, not once their services
  # are accepting connections. Postgres needs a few seconds; Neo4j with APOC needs
  # 30-60s on first start. Block until both are bolt/SQL ready or time out.
  local start

  echo "test-stack: waiting for postgres..." >&2
  start=$SECONDS
  until compose exec -T postgres pg_isready -U "${POSTGRES_USER:-pearscarf}" -d "${POSTGRES_DB:-pearscarf}" >/dev/null 2>&1; do
    if [ $((SECONDS - start)) -ge 60 ]; then
      echo "test-stack: postgres not ready after 60s" >&2
      exit 1
    fi
    sleep 1
  done

  echo "test-stack: waiting for neo4j..." >&2
  start=$SECONDS
  until compose exec -T neo4j cypher-shell -u neo4j -p "${NEO4J_PASSWORD:-password}" "RETURN 1" >/dev/null 2>&1; do
    if [ $((SECONDS - start)) -ge 120 ]; then
      echo "test-stack: neo4j not ready after 120s" >&2
      exit 1
    fi
    sleep 2
  done

  echo "test-stack: ready" >&2
}

case "${1:-}" in
  up)
    compose up -d "${SERVICES[@]}"
    wait_ready
    ;;
  down)
    compose down -v
    wipe_data
    ;;
  reset)
    compose down -v
    wipe_data
    compose up -d "${SERVICES[@]}"
    wait_ready
    ;;
  ps)
    compose ps
    ;;
  *)
    echo "Usage: scripts/test-stack.sh {up|reset|down|ps}" >&2
    exit 1
    ;;
esac
