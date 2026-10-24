#!/usr/bin/env bash
# Real memory + real core together, then the memory demo beats. Run from anywhere:
#   bash core/tests/integration/run_with_memory.sh                    # needs memory/.env (Moss, SpacetimeDB)
#   bash core/tests/integration/run_with_memory.sh --local-backends   # Moss/SpacetimeDB stood in locally
# Memory runs on 8001 (its own default), core on 8000. Logs land in core/tests/out/.
cd "$(dirname "$0")/../.."
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
exec "$PY" -m tests.integration.memory_beats "$@"
