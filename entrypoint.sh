#!/bin/sh
set -eu

log() { echo "entrypoint: $*"; }

wait_for_postgres() {
    attempts=60
    while [ "$attempts" -gt 0 ]; do
        if python - <<'PY' >/dev/null 2>&1
import os, sys
import psycopg
try:
    with psycopg.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        user=os.environ.get("POSTGRES_USER", "pearscarf"),
        password=os.environ.get("POSTGRES_PASSWORD", ""),
        dbname=os.environ.get("POSTGRES_DB", "pearscarf"),
        connect_timeout=2,
    ):
        sys.exit(0)
except Exception:
    sys.exit(1)
PY
        then
            log "postgres ready"
            return 0
        fi
        attempts=$((attempts - 1))
        log "waiting for postgres... (${attempts} attempts left)"
        sleep 2
    done
    log "postgres never became ready" >&2
    exit 1
}

install_experts() {
    if [ ! -d "${EXPERTS_DIR}" ]; then
        log "EXPERTS_DIR=${EXPERTS_DIR} does not exist, skipping install"
        return 0
    fi

    installed=$(psc expert list 2>/dev/null | awk 'NR>2 {print $1}' || true)

    for dir in "${EXPERTS_DIR}"/*/; do
        [ -d "$dir" ] || continue
        [ -f "${dir}manifest.yaml" ] || continue
        name=$(basename "$dir")
        if echo "$installed" | grep -qx "$name"; then
            log "expert ${name} already installed, skipping"
            continue
        fi
        log "installing ${name} from ${dir}"
        if ! psc install --yes "$dir"; then
            log "install of ${name} failed" >&2
            return 1
        fi
    done
}

wait_for_postgres
install_experts

log "exec: $*"
exec "$@"
