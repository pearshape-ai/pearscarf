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

case "${1:-}" in
  up)
    compose up -d "${SERVICES[@]}"
    ;;
  down)
    compose down -v
    wipe_data
    ;;
  reset)
    compose down -v
    wipe_data
    compose up -d "${SERVICES[@]}"
    ;;
  ps)
    compose ps
    ;;
  *)
    echo "Usage: scripts/test-stack.sh {up|reset|down|ps}" >&2
    exit 1
    ;;
esac
