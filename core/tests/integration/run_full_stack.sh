#!/usr/bin/env bash
# Core + memory + browser agent (real services, real demo Chrome), one pass over every intent. Run from anywhere:
#   bash core/tests/integration/run_full_stack.sh
# Uses a running `bash run.sh`, or starts `run.sh --no-tunnel` and stops it afterwards. Logs land in core/tests/out/.
cd "$(dirname "$0")/../.."
PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
exec "$PY" -m tests.integration.full_stack "$@"
