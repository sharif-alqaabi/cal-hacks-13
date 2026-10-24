"""Run core on :8000 with every external API faked (no keys, no YOLO, no network).

  python -m tests.run_offline                 # expects stubs on :8001/:8002 (tests/run_with_stubs.sh style)
  python -m tests.run_offline --with-stubs    # also starts both stubs as subprocesses

Adds one test-only route, POST /_test/bad_llm {"on": true}, which makes the fake LLM answer with a
banned phrase so the safety filter can be demonstrated.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--with-stubs", action="store_true")
    args = p.parse_args()

    procs = []
    if args.with_stubs:
        for mod, port in (("tests.stubs.memory_stub:app", 8001), ("tests.stubs.browser_stub:app", 8002)):
            procs.append(subprocess.Popen([sys.executable, "-m", "uvicorn", mod, "--port", str(port),
                                           "--log-level", "warning"], cwd=CORE))
        os.environ.setdefault("MEMORY_URL", "http://127.0.0.1:8001")
        os.environ.setdefault("BROWSER_URL", "http://127.0.0.1:8002")

    import uvicorn
    from fastapi import Body

    from app import config
    from tests import fakes

    config.MEMORY_URL = os.environ.get("MEMORY_URL", config.MEMORY_URL)
    config.BROWSER_URL = os.environ.get("BROWSER_URL", config.BROWSER_URL)
    f = fakes.install()

    from app.main import app

    @app.post("/_test/bad_llm")
    def bad_llm(body: dict = Body(...)):
        f["llm"].bad = bool(body.get("on"))
        return {"bad": f["llm"].bad}

    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        for pr in procs:
            pr.terminate()


if __name__ == "__main__":
    main()
