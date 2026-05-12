#!/usr/bin/env bash
# Run a pearscarf ER eval against the isolated test stack and capture the report.
#
# Usage:
#   scripts/benchmark.sh <dataset-path> [--debug] [--no-reset]
#
#   <dataset-path>   Path to an eval dataset directory.
#   --debug          Enable debug mode; psc eval dumps per-record LLM prompts/responses
#                    under $BENCHMARK_DEBUG_DIR via `--debug-dir`.
#   --no-reset       Skip the test-stack reset (run against current state).
#
# Environment:
#   BENCHMARK_DEBUG_DIR   Where artifacts land (run logs + LLM traces).
#                         Default: data/test/benchmark-debug
#
# Requires `env/.test.env` (with a real `ANTHROPIC_API_KEY`) and a running
# test stack (`scripts/test-stack.sh up`). The script resets the stack before
# each run unless `--no-reset` is passed.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="env/.test.env"
DEBUG_DIR="${BENCHMARK_DEBUG_DIR:-data/test/benchmark-debug}"

usage() {
  cat >&2 <<'EOF'
Usage: scripts/benchmark.sh <dataset-path> [--debug] [--no-reset]

  <dataset-path>  Path to an eval dataset directory.
  --debug         Enable debug mode (full LLM prompts/responses captured).
  --no-reset      Skip the test-stack reset; run against current state.

Env:
  BENCHMARK_DEBUG_DIR   Where to land run artifacts (default: data/test/benchmark-debug)
EOF
}

DATASET=""
DEBUG=0
RESET=1
for arg in "$@"; do
  case "$arg" in
    --debug)    DEBUG=1 ;;
    --no-reset) RESET=0 ;;
    -h|--help)  usage; exit 0 ;;
    -*)         echo "benchmark: unknown flag '$arg'" >&2; usage; exit 1 ;;
    *)
      if [ -n "$DATASET" ]; then
        echo "benchmark: more than one dataset path given" >&2; exit 1
      fi
      DATASET="$arg"
      ;;
  esac
done

if [ -z "$DATASET" ]; then
  echo "benchmark: missing <dataset-path>" >&2
  usage; exit 1
fi
if [ ! -d "$DATASET" ]; then
  echo "benchmark: dataset path not found: $DATASET" >&2
  exit 1
fi
DATASET_ABS="$(cd "$DATASET" && pwd)"

if [ ! -f "$ENV_FILE" ]; then
  echo "benchmark: $ENV_FILE missing — copy env/.test.env.example first" >&2
  exit 1
fi

# Load test env. .test.env values take precedence (sourced after shell env).
# shellcheck disable=SC1090
set -a; . "$ENV_FILE"; set +a

if [ -z "${ANTHROPIC_API_KEY:-}" ] || [[ "$ANTHROPIC_API_KEY" == sk-test-* ]]; then
  echo "benchmark: ANTHROPIC_API_KEY missing or placeholder — set a real key in $ENV_FILE" >&2
  exit 1
fi

mkdir -p "$DEBUG_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="$DEBUG_DIR/$TS.log"

if [ "$RESET" -eq 1 ]; then
  echo "benchmark: resetting test stack..." >&2
  scripts/test-stack.sh reset >&2
fi

EVAL_ARGS=(eval er --dataset "$DATASET_ABS")
if [ "$DEBUG" -eq 1 ]; then
  EVAL_ARGS+=(--debug --debug-dir "$DEBUG_DIR")
fi

echo "benchmark: psc ${EVAL_ARGS[*]}" >&2
set +e
uv run psc "${EVAL_ARGS[@]}" 2>&1 | tee "$LOG_FILE"
EVAL_EXIT=${PIPESTATUS[0]}
set -e

echo "benchmark: run log $LOG_FILE" >&2
if [ "$DEBUG" -eq 1 ]; then
  echo "benchmark: LLM traces under $DEBUG_DIR/<dataset>_v<ver>_<ts>/" >&2
fi
exit "$EVAL_EXIT"
