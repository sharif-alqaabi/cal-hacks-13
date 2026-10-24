#!/usr/bin/env bash
# Test setup: memory stub, browser stub and core together. Run from core/: bash tests/run_with_stubs.sh
cd "$(dirname "$0")/.."
trap 'kill 0' EXIT
uvicorn tests.stubs.memory_stub:app --port 8001 --log-level warning &
uvicorn tests.stubs.browser_stub:app --port 8002 --log-level warning &
uvicorn app.main:app --host 0.0.0.0 --port 8000
