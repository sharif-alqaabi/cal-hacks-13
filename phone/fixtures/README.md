# Glasses fixtures

Real glasses recordings that let engineers 2–4 work without the hardware. Media is git-ignored;
recordings are shared through the team drive (post the link in the thread). Only this README is committed.

## Record (Engineer 1)

```bash
python -m venv phone/.venv && phone/.venv/bin/pip install -r phone/requirements.txt
phone/.venv/bin/python phone/tools/recorder.py --name demo
```

Set the app's core address to `ws://<this-laptop>:8000/stream`, then walk each beat once.
Hold push-to-talk for each question, and leave a few seconds between beats:

1. Walk toward a chair at eye height, from about 4 m away until it fills the view.
2. Face the crosswalk footage: walk, don't walk, countdown.
3. Set the keys down on a table in view; look away; later ask "where did I put my keys".
4. Look at a teammate and say "this is my brother Sam".
5. Ask "what's in front of me", "what does the signal say", "email Sam that I'm at the Palace of Fine Arts", "yes send it", "I'm lost".

Ctrl+C when done. The file is `phone/fixtures/demo.jsonl`, about 5–10 minutes. Note each beat's start time
in the table below.

## Use

```bash
python phone/replay.py phone/fixtures/demo.jsonl --url $CORE_URL               # whole run, real time
python phone/replay.py phone/fixtures/demo.jsonl --from 12 --to 40 --loop      # one beat, repeated
python phone/replay.py phone/fixtures/demo.jsonl --export out/ --from 12 --to 40 --mp4
```

`--export` writes `frames.mp4` (or JPEGs) plus `turn_NN.wav` per push-to-talk turn: the files
`core/tests/fixtures/README.md` asks for under `real/`.

| Recording | Beat | From (s) | To (s) |
|---|---|---|---|
| demo.jsonl | chair walk | | |
| | crosswalk | | |
| | keys set down / recall | | |
| | "this is my brother Sam" | | |
| | scripted questions | | |
