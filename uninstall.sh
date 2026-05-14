#!/usr/bin/env bash
# pearscarf uninstaller. Stops + removes the local pearscarf stack, wipes all
# data, and deletes the install directory.
#
# Two ways to run:
#   1. In-tree (preferred when you know where pearscarf is):
#        cd /path/to/your/pearscarf && bash uninstall.sh
#
#   2. One-line via curl (prompts for the install path):
#        bash <(curl -fsSL https://raw.githubusercontent.com/pearshape-ai/pearscarf/main/uninstall.sh)
#
# DESTRUCTIVE: removes containers, volumes, the locally-built pearscarf image,
# and the entire install directory (including all postgres / neo4j / qdrant
# data on disk). There is no undo. Requires you to type 'wipe' to confirm.

set -euo pipefail

TOTAL_STEPS=4

# ---- output helpers --------------------------------------------------------

if [ -t 1 ]; then
    BOLD=$'\033[1m'; DIM=$'\033[2m'; RESET=$'\033[0m'
    GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; YELLOW=$'\033[0;33m'; CYAN=$'\033[0;36m'
else
    BOLD=''; DIM=''; RESET=''; GREEN=''; RED=''; YELLOW=''; CYAN=''
fi

banner() {
    printf '\n%s' "$YELLOW"
    cat <<'BANNER'
                                             __
   _ __   ___  __ _ _ __ ___  ___ __ _ _ __ / _|
  | '_ \ / _ \/ _` | '__/ __|/ __/ _` | '__| |_
  | |_) |  __/ (_| | |  \__ \ (_| (_| | |  |  _|
  | .__/ \___|\__,_|_|  |___/\___\__,_|_|  |_|
  |_|
BANNER
    printf '%s' "$RESET"
    printf "\n  ${BOLD}uninstaller${RESET}${DIM} ─ this will wipe pearscarf and its data from this host${RESET}\n\n"
}
step()  { printf "\n${BOLD}[%s/%s] %s${RESET}\n" "$1" "$TOTAL_STEPS" "$2"; }
ok()    { printf "      ${GREEN}✓${RESET} %s\n" "$1"; }
warn()  { printf "      ${YELLOW}!${RESET} %s\n" "$1"; }
fail()  { printf "      ${RED}✗${RESET} %s\n" "$1" >&2; }
info()  { printf "      ${DIM}%s${RESET}\n" "$1"; }

banner

# ---- step 1/4: locate the install -----------------------------------------

step 1 "Locating the pearscarf install"

install_path=""
if [ -f "./docker-compose.yml" ] && [ -f "./.env" ] && grep -q "pearscarf:" "./docker-compose.yml" 2>/dev/null; then
    install_path="$(pwd)"
    ok "Detected install at $install_path"
else
    read -r -p "      Pearscarf install path: " install_path
    install_path="${install_path%/}"
    if [ ! -d "$install_path" ]; then
        fail "Directory not found: $install_path"
        exit 1
    fi
    if [ ! -f "$install_path/docker-compose.yml" ] || ! grep -q "pearscarf:" "$install_path/docker-compose.yml" 2>/dev/null; then
        fail "$install_path doesn't look like a pearscarf install"
        info "(no docker-compose.yml with a 'pearscarf:' service)"
        exit 1
    fi
    ok "Found install at $install_path"
fi

# ---- step 2/4: confirm -----------------------------------------------------

step 2 "Confirming destructive action"

printf "      This will:\n"
printf "        ${RED}1.${RESET} Stop and remove all pearscarf containers\n"
printf "        ${RED}2.${RESET} Remove their named volumes (DESTROYS ALL DATA — facts, records, embeddings, drafts)\n"
printf "        ${RED}3.${RESET} Remove the locally-built pearscarf image\n"
printf "        ${RED}4.${RESET} Delete the entire directory: %s\n" "$install_path"
printf "\n      ${BOLD}${RED}There is no undo.${RESET}\n\n"

read -r -p "      Type ${BOLD}wipe${RESET} to confirm, anything else to abort: " confirmation
if [ "$confirmation" != "wipe" ]; then
    info "Aborted. Nothing was changed."
    exit 0
fi

# ---- step 3/4: docker teardown --------------------------------------------

step 3 "Stopping containers and removing volumes + locally-built images"

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    if (cd "$install_path" && docker compose down -v --rmi local >/dev/null 2>&1); then
        ok "Containers stopped, volumes + locally-built images removed"
    else
        warn "docker compose down completed with errors"
        info "Run manually if needed: (cd $install_path && docker compose down -v --rmi local)"
    fi
else
    warn "Docker daemon not running — skipping container/volume/image teardown"
    info "You may have leftover containers. Inspect via 'docker ps -a' and clean manually."
fi

# ---- step 4/4: filesystem teardown ----------------------------------------

step 4 "Deleting the install directory"

rm -rf "$install_path"
ok "Removed $install_path"

# ---- done ------------------------------------------------------------------

printf "\n  ${GREEN}${BOLD}╭─────────────────────────────────────────╮${RESET}\n"
printf "  ${GREEN}${BOLD}│  pearscarf has been wiped from this host  │${RESET}\n"
printf "  ${GREEN}${BOLD}╰─────────────────────────────────────────╯${RESET}\n\n"

printf "  ${DIM}Optional — reclaim Docker build cache across all projects:${RESET}\n"
printf "    ${CYAN}docker system prune -a${RESET}\n\n"
