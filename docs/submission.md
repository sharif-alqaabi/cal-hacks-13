# Submission package (Eng 4)

Devpost closes **Sun Oct 25, 9:00 AM**; we submit by **8:30 AM**. Judging is 10:30 AM to 12:30 PM, all four of us at the table.

## Checklist

| ID | Deliverable | Due | Status |
|---|---|---|---|
| S-1 | One quote, with permission, from a blind or low-vision person or an orientation-and-mobility instructor | Sat 6 PM | ☐ |
| S-2 | Root [README](../README.md): setup, sponsor tools, Cartesia features, limitations, no keys | Sat 11 PM | ☐ draft written; phone and dashboard rows to fill in |
| S-3 | Devpost draft: all four teammates added, tracks selected | Sat 11 PM | ☐ |
| S-4 | Backup demo video from checkpoint clips plus one full run | Sat 11 PM | ☐ |
| S-5 | Final submission | Sun 8:30 AM | ☐ |

Before submitting: `git grep -nE "sk-ant|sk-or-|TYPESAFE_API_KEY=.+|ANTHROPIC_API_KEY=.+"` finds nothing; the repo is
public; commit history starts at the event; every `.env.example` has empty values.

## S-1: the user quote

Ask in `#1-ask-mentors` tonight, and ask any accessibility mentor or orientation-and-mobility instructor at the venue.

> Hi! We're building a voice assistant on Meta Ray-Ban glasses for blind and low-vision people: it warns about
> obstacles, reads walk signals, remembers where you put things, and sends emails by voice with a read-back before
> anything is sent. Is anyone here blind or low-vision, or an O&M instructor, who'd talk to us for 10 minutes?
> We'd love one quote for our submission, only with your permission and with whatever name you prefer.

Questions: What takes the longest in a normal workday? What do you ask sighted people to check for you? What would
make you trust (or distrust) a device that talks to you while you walk? Would an email read-back help or annoy you?

Record: the exact words, the name and description they agree to ("a blind software tester"), and that they said
yes to it being published. Quote: _____

## S-3: Devpost draft

**Tracks**: Meta (Bringing People Closer Together), Anthropic, Cartesia, Moss, SpacetimeDB. Confirm how many one
submission may enter; if limited, drop in reverse order. General prizes are automatic.

**Tagline**: Meta Ray-Ban glasses that describe the way ahead, remember what you saw, and send your email, asking first.

**Inspiration**: start with the S-1 quote. Blind and low-vision adults rely on a cane and on other people for things a
camera can now help with: reading a crossing signal, checking a packed order, sending an email, finding their keys.

**What it does**: one voice loop through the glasses.
- Obstacle warnings while walking ("Stop, chair ahead, slightly left.") from a detector running on the laptop.
- "What does the signal say?" describes the signal and moving cars, and never says "safe".
- "Where did I put my keys?" answers with time and place from a memory of what the glasses saw; the thumbnail shows on
  the family dashboard.
- "Email Sam that I'm at the Palace of Fine Arts": the laptop drafts it in Gmail, reads it back, and sends only after
  "send", then checks the Sent folder before saying it went out.
- "I'm lost" alerts the family dashboard with the last known place.

**How we built it**: the architecture slide plus the sponsor table from the README. Highlight: Cartesia Ink-2 and
Sonic-3.5 are the entire interface; Jev routes each utterance and, through Jev Ultrafast, picks every browser
action; Claude Haiku sees, Claude Sonnet reasons; Moss searches memory in milliseconds; SpacetimeDB is both the memory
timeline and the live dashboard.

**Challenges**: open-ear speakers that judges can't hear (the mirror page); an 8 kHz glasses mic; making the browser
agent provably unable to send without consent (two guard layers plus Sent-folder verification); never overclaiming
safety.

**What we learned / what's next**: on-device fallback for vision, more mail providers, a work-mode pilot with an
employer, and a privacy review of stored memories.

**Built with**: Meta Wearables Device Access Toolkit, Cartesia Ink-2, Cartesia Sonic-3.5, TypeSafe Jev, Jev Ultrafast,
Claude Haiku 5.5, Claude Sonnet 5.5, Moss, SpacetimeDB, Ultralytics YOLO, FastAPI, React, Python.

## S-4: backup video (about 2 minutes, real speed)

Shot list, recorded Saturday night from each owner's checkpoint clips plus one full run on the demo laptop:

1. 0:00 The keys-recall moment (Devpost checklist: open with it). Keys set down on camera, later "Where did I put my
   keys?", spoken answer, thumbnail appears on the dashboard.
2. Walking toward a chair: "Stop, chair ahead, slightly left."
3. Crosswalk footage: "The walk sign is on. A car is moving from your left."
4. Email: screen split between Chrome and `http://localhost:8002/trace`. Show the guard line ("Held before Send"), the
   read-back, then "Send", and the verify line "Found it in the Sent folder". Then repeat with "cancel".
5. "I'm lost": the family dashboard alert.
6. Closing card: architecture and the four responsibility points.

Laptop audio must carry every spoken reply (the glasses speakers are open-ear). Keep the full-run file on the demo
laptop and a phone, ready to play if the venue wifi fails.

## S-5: final checks (Sun 7 to 8:30 AM)

- All four services merged to `main` and running on the demo laptop (`/health` 200 on 8000, 8001, 8002).
- `cd browser && uv run python runs.py --email 2 --lookup 1` against the real Gmail account passes.
- Pre-warm TypeSafe and Claude with one run of each beat before 10:30 AM.
- Devpost: video link, repo link, all teammates, tracks, the quote. Submit, then re-open to confirm it saved.
