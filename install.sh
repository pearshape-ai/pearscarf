#!/usr/bin/env bash
# pearscarf installer.
#
# One-line install:
#   bash <(curl -fsSL https://raw.githubusercontent.com/pearshape-ai/pearscarf/main/install.sh)
#
# Clones the pearscarf source into a directory of your choice, generates a
# `.env` with the keys you provide + auto-random DB passwords, then runs
# `docker compose up -d --build` against the bundled docker-compose.yml to
# bring up postgres + neo4j + qdrant + pearscarf. Verifies the MCP layer
# serves real tool calls before declaring success.
#
# No public Docker image — the image is built locally as part of the install.

set -euo pipefail

REPO_URL="${PEARSCARF_REPO:-https://github.com/pearshape-ai/pearscarf.git}"
TARBALL_URL="${PEARSCARF_TARBALL:-https://github.com/pearshape-ai/pearscarf/archive/refs/heads/main.tar.gz}"
DEFAULT_PATH="$(pwd)/pearscarf"
HEALTH_URL_INTERNAL="http://localhost:8090/health"
MCP_URL_INTERNAL="http://localhost:8090/sse"
TOTAL_STEPS=7

# ---- output helpers --------------------------------------------------------

if [ -t 1 ]; then
    BOLD=$'\033[1m'; DIM=$'\033[2m'; RESET=$'\033[0m'
    GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; YELLOW=$'\033[0;33m'; CYAN=$'\033[0;36m'
else
    BOLD=''; DIM=''; RESET=''; GREEN=''; RED=''; YELLOW=''; CYAN=''
fi

banner() {
    printf '\n%s' "$GREEN"
    cat <<'BANNER'
                                             __
   _ __   ___  __ _ _ __ ___  ___ __ _ _ __ / _|
  | '_ \ / _ \/ _` | '__/ __|/ __/ _` | '__| |_
  | |_) |  __/ (_| | |  \__ \ (_| (_| | |  |  _|
  | .__/ \___|\__,_|_|  |___/\___\__,_|_|  |_|
  |_|
BANNER
    printf '%s' "$RESET"
    printf "\n  ${BOLD}installer${RESET}${DIM} ─ shared operational brain for teams of AI coworkers${RESET}\n\n"
}
step()    { printf "\n${BOLD}[%s/%s] %s${RESET}\n" "$1" "$TOTAL_STEPS" "$2"; }
ok()      { printf "      ${GREEN}✓${RESET} %s\n" "$1"; }
warn()    { printf "      ${YELLOW}!${RESET} %s\n" "$1"; }
fail()    { printf "      ${RED}✗${RESET} %s\n" "$1" >&2; }
info()    { printf "      ${DIM}%s${RESET}\n" "$1"; }
field()   { printf "      %s ${DIM}%s${RESET}\n" "$1" "$2"; }

# ---- spinner for long-running ops ------------------------------------------

spin() {
    local pid=$1
    local label=$2
    local chars='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    local start
    start=$(date +%s)
    local i=0
    if [ ! -t 1 ]; then
        wait "$pid"
        local rc=$?
        printf "      %s %s (done in %ds)\n" "$([ $rc -eq 0 ] && printf "${GREEN}✓${RESET}" || printf "${RED}✗${RESET}")" "$label" $(( $(date +%s) - start ))
        return $rc
    fi
    while kill -0 "$pid" 2>/dev/null; do
        local elapsed=$(( $(date +%s) - start ))
        local char=${chars:$((i % ${#chars})):1}
        printf "\r      ${CYAN}%s${RESET} %s ${DIM}(%ds)${RESET}" "$char" "$label" "$elapsed"
        i=$((i+1))
        sleep 0.1
    done
    wait "$pid"
    local rc=$?
    local elapsed=$(( $(date +%s) - start ))
    if [ $rc -eq 0 ]; then
        printf "\r      ${GREEN}✓${RESET} %s ${DIM}(done in %ds)${RESET}\n" "$label" "$elapsed"
    else
        printf "\r      ${RED}✗${RESET} %s ${DIM}(failed after %ds)${RESET}\n" "$label" "$elapsed"
    fi
    return $rc
}

banner

# ---- step 1/7: pre-reqs ----------------------------------------------------

step 1 "Checking pre-requisites"

if ! command -v docker >/dev/null 2>&1; then
    fail "docker not found on PATH"
    info "Install Docker: https://docs.docker.com/get-docker/"
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    fail "Docker daemon is not running"
    info "Start Docker Desktop (or your daemon equivalent) and re-run."
    exit 1
fi
ok "Docker daemon: running"

if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:8090 -sTCP:LISTEN >/dev/null 2>&1; then
    fail "port 8090 is already in use"
    info "PearScarf MCP SSE needs that port. Free it (or stop the conflicting service) and re-run."
    info "Inspect with: lsof -nP -iTCP:8090 -sTCP:LISTEN"
    exit 1
fi
if command -v lsof >/dev/null 2>&1 && lsof -nP -iTCP:8091 -sTCP:LISTEN >/dev/null 2>&1; then
    fail "port 8091 is already in use"
    info "PearScarf MCP HTTP needs that port. Free it (or stop the conflicting service) and re-run."
    info "Inspect with: lsof -nP -iTCP:8091 -sTCP:LISTEN"
    exit 1
fi
ok "Ports 8090 (SSE) + 8091 (HTTP): free"

# ---- step 2/7: inputs ------------------------------------------------------

step 2 "Collecting input"

read -r -p "      Install path [$DEFAULT_PATH]: " install_path
install_path="${install_path:-$DEFAULT_PATH}"
if [ -e "$install_path" ]; then
    fail "Path already exists: $install_path"
    info "Move or remove it, then re-run."
    exit 1
fi

read -r -s -p "      Anthropic API key (extraction): " anthropic_key
echo ""
[ -n "$anthropic_key" ] || { fail "An Anthropic API key is required."; exit 1; }

read -r -s -p "      OpenAI API key   (embeddings):  " openai_key
echo ""
[ -n "$openai_key" ] || { fail "An OpenAI API key is required."; exit 1; }
ok "Inputs collected"

# ---- step 3/7: fetch source ------------------------------------------------

step 3 "Fetching pearscarf source"

if command -v git >/dev/null 2>&1; then
    info "git available — using git clone"
    git clone --quiet --depth 1 "$REPO_URL" "$install_path"
    ok "Cloned into $install_path"
else
    info "git not found — downloading source tarball"
    mkdir -p "$install_path"
    if ! curl -fsSL "$TARBALL_URL" | tar -xz --strip-components=1 -C "$install_path"; then
        fail "Failed to download or extract source tarball."
        info "Install git (https://git-scm.com/) or check your network, then re-run."
        rmdir "$install_path" 2>/dev/null || true
        exit 1
    fi
    ok "Extracted into $install_path"
fi

# ---- step 4/7: generate .env -----------------------------------------------

step 4 "Generating local .env"

postgres_password="$(openssl rand -hex 24)"
neo4j_password="$(openssl rand -hex 24)"

cat > "$install_path/.env" <<EOF
# pearscarf — generated by install.sh. Edit at your own risk.

# API keys
ANTHROPIC_API_KEY=$anthropic_key
OPENAI_API_KEY=$openai_key

# Auto-random DB passwords (kept local, not pushed anywhere).
POSTGRES_PASSWORD=$postgres_password
NEO4J_PASSWORD=$neo4j_password

# Host port mappings. Pearscarf MCP exposes two transports: SSE on 8090
# (legacy), HTTP on 8091 (recommended). Internal services are shifted into
# the high-3xxxx range so they almost never conflict with locally-running
# postgres / neo4j / qdrant / pgadmin.
MCP_PORT=8090
MCP_HTTP_PORT=8091
POSTGRES_PORT=35432
QDRANT_HTTP_PORT=36333
QDRANT_GRPC_PORT=36334
NEO4J_HTTP_PORT=37474
NEO4J_BOLT_PORT=37687
PGADMIN_PORT=35050
EOF
chmod 600 "$install_path/.env"
ok "Wrote $install_path/.env (chmod 600)"
field "MCP ports:" "8090 (SSE), 8091 (HTTP)"
field "Internal ports:" "35432 (postgres), 36333/36334 (qdrant), 37474/37687 (neo4j), 35050 (pgadmin)"

# ---- step 5/7: build + start ----------------------------------------------

step 5 "Building image + starting the stack"
info "First build takes ~2 minutes. Containers stay quiet after; only this step is slow."

(cd "$install_path" && docker compose up -d --build >/dev/null 2>&1) &
spin $! "docker compose up -d --build" || {
    fail "docker compose failed"
    info "Inspect: (cd $install_path && docker compose logs)"
    exit 1
}

# ---- step 6/7: health + MCP verification -----------------------------------

step 6 "Verifying the MCP is live"

# (a) HTTP health endpoint
for i in $(seq 1 60); do
    if curl -fsS "$HEALTH_URL_INTERNAL" >/dev/null 2>&1; then
        ok "Health endpoint (port 8090): 200"
        break
    fi
    if [ "$i" -eq 60 ]; then
        fail "Health endpoint did not return 200 within 60s."
        info "Inspect logs: (cd $install_path && docker compose logs pearscarf)"
        exit 1
    fi
    sleep 1
done

# (b) Real MCP tool call from inside the container (using HTTP transport)
if (cd "$install_path" && docker compose exec -T pearscarf python - <<'PYEOF' >/dev/null 2>&1
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async def main():
    async with streamable_http_client("http://localhost:8091/mcp") as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()
            await session.call_tool("get_schema", {})

asyncio.run(asyncio.wait_for(main(), timeout=15))
PYEOF
); then
    ok "MCP probe (get_schema via HTTP): responded"
else
    fail "MCP did not respond to a get_schema call within 15s."
    info "Health passed but the MCP layer may not be fully ready."
    info "Inspect logs: (cd $install_path && docker compose logs pearscarf)"
    exit 1
fi

# ---- step 7/7: done --------------------------------------------------------

step 7 "Done"

printf "\n  ${CYAN}${BOLD}╭──────────────────────────────────────────────────╮${RESET}\n"
printf "  ${CYAN}${BOLD}│  PearScarf MCP URLs                              │${RESET}\n"
printf "  ${CYAN}${BOLD}│${RESET}                                                  ${CYAN}${BOLD}│${RESET}\n"
printf "  ${CYAN}${BOLD}│${RESET}    ${BOLD}http://localhost:8091/mcp${RESET} (HTTP, recommended) ${CYAN}${BOLD}│${RESET}\n"
printf "  ${CYAN}${BOLD}│${RESET}    ${BOLD}http://localhost:8090/sse${RESET} (SSE, legacy)       ${CYAN}${BOLD}│${RESET}\n"
printf "  ${CYAN}${BOLD}╰──────────────────────────────────────────────────╯${RESET}\n\n"

printf "  ${BOLD}Next:${RESET}\n"
printf "    Install the AI workforce against this MCP:\n"
printf "      ${CYAN}bash <(curl -fsSL https://raw.githubusercontent.com/pearshape-ai/claude-workforce/main/install.sh)${RESET}\n"
printf "    Paste the URL above when the workforce installer asks for it.\n\n"

printf "  ${BOLD}Operate:${RESET}\n"
printf "    Stop the stack:        ${CYAN}cd %s && docker compose down${RESET}\n" "$install_path"
printf "    Tail pearscarf logs:   ${CYAN}cd %s && docker compose logs -f pearscarf${RESET}\n" "$install_path"
printf "    Uninstall completely:  ${CYAN}cd %s && bash uninstall.sh${RESET}\n\n" "$install_path"
