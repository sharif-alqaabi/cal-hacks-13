# Cartesia

Our users are blind or low-vision, so they can't use a screen. They talk to the glasses and the glasses talk back,
and Cartesia handles both directions. The code is in [`core/app/stt.py`](core/app/stt.py) and
[`core/app/tts.py`](core/app/tts.py).

## What we use

Speech to text is Ink-2. When you hold the button, we open a websocket to Cartesia and stream the mic audio in
100 ms chunks. When you let go, we send `finalize` and use the final transcript. We pass keyterms like "Sam",
"crosswalk" and "I'm lost" so it gets our demo words right.

Text to speech is Sonic-3.5. We send one request per sentence, so the first sentence starts playing while the
next one is still being made. The audio goes back to the phone over our `/stream` websocket and plays on the
glasses.

We play speech at 1.75x, because screen-reader users tend to listen fast. Sonic goes up to 1.5x, so we ask for
that and speed it up the rest of the way ourselves without changing the pitch.

On startup we generate 118 fixed lines ahead of time and cache them to disk: all 100 obstacle warnings ("Chair
coming up ahead."), the crosswalk signal answers, and the fallback lines like "Working on it." Obstacle warnings
only ever come from this cache, so they play instantly. They're marked urgent, which makes the phone cut off
whatever it's saying and play the warning right away.

## Limitations

- Anything that isn't cached needs wifi. If the connection drops, warnings still play but it can't hear or
  answer questions.
- The cache gets filled the first time it starts with a connection. Until then, a missing warning plays in the
  phone's built-in voice.
- We call the REST endpoint once per sentence instead of using the streaming TTS websocket, so each sentence
  waits for its own round trip.
- It's push-to-talk only. Talking over a reply doesn't stop it; pressing the button does.
- Past 1.5x the speed-up is ours, not Sonic's, so it can sound slightly rougher.
- English only, one voice, and the keyterms are tuned for our demo.
