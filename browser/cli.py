"""Stands in for core: type a goal, hear the read-back, answer y/n.

    uv run python cli.py "email Sam that I'm at the Palace of Fine Arts"
    uv run python cli.py --say "when does Ace Hardware on Polk Street close today"
"""
import argparse
import subprocess
import time

import httpx


def speak(text: str, aloud: bool) -> None:
    print(f"  says: {text}")
    if aloud:
        subprocess.run(["say", text], check=False)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("goal", nargs="?", help="what the wearer said; omit to type goals in a loop")
    p.add_argument("--url", default="http://127.0.0.1:8002")
    p.add_argument("--say", action="store_true", help="speak replies with macOS say")
    p.add_argument("--yes", action="store_true", help="answer yes without asking")
    p.add_argument("--no", action="store_true", help="answer no without asking")
    a = p.parse_args()

    with httpx.Client(base_url=a.url, timeout=60) as c:
        goals = [a.goal] if a.goal else iter(lambda: input("\ngoal> ").strip(), "")
        for goal in goals:
            t0 = time.perf_counter()
            r = c.post("/task", json={"goal": goal}).json()
            print(f"  /task {time.perf_counter() - t0:.1f}s  task_id={r['task_id']} needs_confirm={r['needs_confirm']}")
            speak(r["say"], a.say)
            if not r["needs_confirm"]:
                continue
            yes = a.yes or (not a.no and input("  send? [y/N] ").strip().lower() in {"y", "yes", "send"})
            t0 = time.perf_counter()
            say = c.post("/confirm", json={"task_id": r["task_id"], "yes": yes}).json()["say"]
            print(f"  /confirm yes={yes} {time.perf_counter() - t0:.1f}s")
            speak(say, a.say)


if __name__ == "__main__":
    main()
