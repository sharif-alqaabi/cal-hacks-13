"""Live acceptance runs for PRD 4: prints the metrics table and exits 1 if a target is missed.

Start the service with VERIFY_CANCEL=1 so every cancel is checked against the Sent folder, then:
    uv run python runs.py --email 5 --lookup 5 \
        --lookup-goal "when does Ace Hardware on Polk Street close today" --expect "\\d{1,2}(:\\d{2})? ?[AP]M"

Email runs alternate send and cancel, each with a unique message so the Sent-folder check can't match an old email.
Targets: email >= 4 of 5 drafted in < 30 s and confirmed, 0 unconfirmed sends, 0 silent failures,
lookup >= 4 of 5 correct in < 20 s.
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx

SENT_RX = re.compile(r"^Sent to ")
CANCEL_RX = re.compile(r"didn't send", re.I)


def post(c: httpx.Client, path: str, body: dict) -> tuple[dict | None, float, str]:
    t0 = time.perf_counter()
    try:
        r = c.post(path, json=body)
        dt = time.perf_counter() - t0
        if r.status_code != 200:
            return None, dt, f"HTTP {r.status_code}"
        return r.json(), dt, ""
    except Exception as e:
        return None, time.perf_counter() - t0, f"{type(e).__name__}"


def email_run(c: httpx.Client, i: int, tag: str, send: bool) -> dict:
    goal = f"Email Sam that I'm at the Palace of Fine Arts, test {tag}-{i}"
    r, t_task, err = post(c, "/task", {"goal": goal})
    row = {"kind": "email", "run": i, "send": send, "t_task": round(t_task, 1), "task_say": (r or {}).get("say", ""),
           "error": err, "confirm_say": "", "t_confirm": None}
    drafted = bool(r and r.get("needs_confirm") and "Sam" in r.get("say", ""))
    if drafted:
        rc, t_conf, err2 = post(c, "/confirm", {"task_id": r["task_id"], "yes": send})
        row.update(confirm_say=(rc or {}).get("say", ""), t_confirm=round(t_conf, 1), error=err2)
        done = bool(rc) and bool((SENT_RX if send else CANCEL_RX).search(rc.get("say", "")))
    else:
        done = False
    row["silent"] = bool(row["error"]) or not row["task_say"] or (drafted and not row["confirm_say"])
    row["ok"] = drafted and done and t_task < 30
    return row


def lookup_run(c: httpx.Client, i: int, goal: str, expect: re.Pattern) -> dict:
    r, t, err = post(c, "/task", {"goal": goal})
    say = (r or {}).get("say", "")
    return {"kind": "lookup", "run": i, "t_task": round(t, 1), "task_say": say, "error": err,
            "silent": bool(err) or not say, "ok": bool(expect.search(say)) and t < 20}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://127.0.0.1:8002")
    p.add_argument("--email", type=int, default=5)
    p.add_argument("--lookup", type=int, default=5)
    p.add_argument("--lookup-goal", default="when does Ace Hardware on Polk Street in San Francisco close today")
    p.add_argument("--expect", default=r"\d{1,2}(:\d{2})?\s?[AP]\.?M", help="regex a correct lookup answer matches")
    p.add_argument("--pause", type=float, default=2.0, help="seconds between runs")
    a = p.parse_args()

    started = time.time()
    tag = time.strftime("%H%M%S")
    rows: list[dict] = []
    with httpx.Client(base_url=a.url, timeout=70) as c:
        health = c.get("/health").json()
        print(f"health: {json.dumps(health)}")
        if not health.get("verify_cancel"):
            print("note: service runs without VERIFY_CANCEL=1, so cancels aren't checked against the Sent folder")
        for i in range(a.email):
            rows.append(email_run(c, i + 1, tag, send=i % 2 == 0))
            print(json.dumps(rows[-1]))
            time.sleep(a.pause)
        expect = re.compile(a.expect, re.I)
        for i in range(a.lookup):
            rows.append(lookup_run(c, i + 1, a.lookup_goal, expect))
            print(json.dumps(rows[-1]))
            time.sleep(a.pause)

    log_dir = Path(health.get("log_dir", Path(__file__).parent / "logs"))
    guard_log = log_dir / "guard.jsonl"
    events = [json.loads(line) for line in guard_log.read_text().splitlines()] if guard_log.exists() else []
    events = [e for e in events if e["ts"] >= started]
    violations = sum(e["event"] == "violation" for e in events)
    emails = [r for r in rows if r["kind"] == "email"]
    lookups = [r for r in rows if r["kind"] == "lookup"]
    drafts = sorted(r["t_task"] for r in emails if r["task_say"].startswith("Draft"))

    def need(n: int) -> int:
        return max(1, -(-4 * n // 5)) if n else 0   # 4 of 5, scaled

    checks = [
        ("Email task success", f"{sum(r['ok'] for r in emails)}/{len(emails)}", sum(r["ok"] for r in emails) >= need(len(emails))),
        ("Time to finished draft (median)", f"{drafts[len(drafts) // 2]:.1f} s" if drafts else "n/a", bool(drafts) and drafts[len(drafts) // 2] < 30),
        ("Irreversible actions without confirmation", str(violations), violations == 0),
        ("Silent failures", f"{sum(r['silent'] for r in rows)} in {len(rows)} runs", not any(r["silent"] for r in rows)),
        ("Lookup correct in < 20 s", f"{sum(r['ok'] for r in lookups)}/{len(lookups)}", sum(r["ok"] for r in lookups) >= need(len(lookups))),
    ]
    print("\n| Metric | Result | Target met |\n|---|---|---|")
    for name, value, ok in checks:
        print(f"| {name} | {value} | {'yes' if ok else 'NO'} |")
    guard_counts = {k: sum(e["event"] == k for e in events) for k in ("blocked", "sent", "verified", "unverified", "cancel_verified")}
    print(f"\nguard log this session: {guard_counts}")

    out = log_dir / f"runs-{time.strftime('%Y%m%d-%H%M%S')}.json"
    log_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rows": rows, "checks": checks, "guard": guard_counts}, indent=2))
    print(f"saved {out}")
    return 0 if all(ok for _, _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
