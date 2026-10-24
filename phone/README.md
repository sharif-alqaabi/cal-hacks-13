# phone: glasses & phone relay (part 1)

An iPhone app that turns Meta Ray-Ban glasses into core's camera, mic and speaker (PRD 1).
It streams ~5 fps JPEG frames and push-to-talk audio to `ws://<laptop>:8000/stream`, and plays
every `say` from core through the glasses. Message shapes are core's: [`core/contracts/CONTRACTS.md`](../core/contracts/CONTRACTS.md).

## Build and install

Needs Xcode 26+ and XcodeGen (`brew install xcodegen`).

```bash
cd phone/ios
./setup.sh                 # creates Config.xcconfig from the example, generates GlassesRelay.xcodeproj
open GlassesRelay.xcodeproj
```

1. In `Config.xcconfig` set `DEVELOPMENT_TEAM` (Xcode > Settings > Accounts) and a unique `RELAY_BUNDLE_ID`.
2. **Signing:** a free personal Apple team cannot sign the Hotspot Configuration and Wi-Fi Info
   entitlements in `GlassesRelay.entitlements`. If signing fails, set
   `RELAY_ENTITLEMENTS = GlassesRelay/GlassesRelay-free.entitlements` and rerun `./setup.sh`.
   Read *Streaming risk* below before you rely on that.
3. On the iPhone, open the Meta AI app, pair the glasses, and turn on **Developer Mode** (Settings,
   then the glasses' developer settings). With Developer Mode on, `META_APP_ID` and `CLIENT_TOKEN`
   can stay empty.
4. Run on the phone from Xcode. In the app: **Settings > Connect glasses** opens Meta AI to
   register. The camera permission prompt also opens Meta AI the first time the stream starts.

Check first that your glasses model and firmware are supported:
https://wearables.developer.meta.com/docs/develop/dat/version-dependencies/

## Using it

- The whole screen is one **hold-to-talk** area. VoiceOver passes touches straight through
  (`allowsDirectInteraction`), so you hold it with one finger; no double-tap needed.
- Spoken cues: "Connected", "Connection lost. Reconnecting.", "Reconnected", "Paused",
  "Glasses resumed", "Camera on", "Not connected" (talking while offline).
- The **Settings** sheet holds the core address, camera source and glasses registration.
- **Camera source:**
  - *Glasses camera* is the default.
  - *Phone camera (fallback)* is PRD G-11: switch in one tap, with no backend change.
  - *Mock glasses* uses Meta's MockDeviceKit and only appears in Debug builds.
- The core address takes `ws://host:8000/stream`, `wss://tunnel/stream` or plain `http://host:8000`.

## Behaviour that matters to core

| What | How |
|---|---|
| Frames | Long side ≤ 640 px at JPEG q0.7, sent ~5 fps. Glasses frames are portrait 9:16 (e.g. 360×640), so read `w`/`h`. |
| Back-pressure | At most 2 frames in flight. Extra frames are dropped, never queued, so lag can't build up. |
| `ts` | Unix seconds (float), as in `contracts/stream.py`. |
| Audio | 16-bit mono in 100 ms chunks, only while the button is held. 8000 Hz from the glasses (HFP), 16000 Hz from the phone mic. The last partial chunk is sent before `ptt up`. |
| `say` | Non-urgent replies are queued and played in order. Urgent replies clear the queue and interrupt. An empty `pcm16_b64` is read out with the on-device voice. Pressing talk stops playback (barge-in). |
| `snap` | Answered with the latest frame at long side ≤ 1280 px, carrying `snap_id`. |
| Pause | Glasses tapped, removed or folded means nothing is sent, and the held frame is dropped. Frames are never written to disk. |
| Reconnect | Ping every 1 s; no pong for 3 s counts as a drop. Retries at 0.5 s, 1 s, then every 2 s. |

## Streaming risk (test this first with the real glasses)

Meta's iOS guide says camera streaming uses the glasses' Wi-Fi: it needs the Hotspot
Configuration entitlement, and without Local Network permission or Wi-Fi it "continues over
Bluetooth LE without streaming". If the phone joins the glasses' Wi-Fi, it may lose venue wifi,
and then a LAN `ws://` address won't reach the laptop. Mitigations, in order:

1. Use a paid Apple team so the full entitlements sign.
2. Point the core address at a tunnel (`cloudflared tunnel --url http://localhost:8000` gives a
   `wss://…/stream` URL), which works over cellular too. Cellular isn't a personal hotspot, so it's
   allowed at the venue.
3. Fall back to the phone camera (Settings > Camera).

## Testing without the phone

`GlassesRelay/CoreLink.swift` and `Messages.swift` are Foundation-only. They were exercised on a Mac
against `python -m tests.run_offline --with-stubs` (core with faked APIs) using the core fixtures:

- **Chair walk:** urgent "Stop, chair ahead" twice, 3 s apart.
- **Keys:** `keys.wav` over push-to-talk answered 71 ms after `ptt up`.
- **Describe:** `snap` answered, then a two-sentence reply.
- **Reconnect:** core was killed and restarted mid-stream, and the link came back on its own.

## Fixtures for teammates (PRD G-10)

`tools/recorder.py` stands in for core: it records everything the app sends, checks it against core's
contract, and answers with mock `say`/`snap`. `replay.py` plays a recording into any `CORE_URL` in
real time, or exports frames and per-turn WAVs. See [fixtures/README.md](fixtures/README.md).
Tested: a recorded demo run replayed into offline core gave the same chair warnings and push-to-talk
turns, and the exported WAVs are byte-identical to the source audio.

## Layout

| Path | What | PRD |
|---|---|---|
| `ios/project.yml`, `ios/setup.sh` | XcodeGen spec; the generated `.xcodeproj` and `Config.xcconfig` are git-ignored | |
| `GlassesRelayApp.swift` | `Wearables.configure()`, Meta AI URL callback | G-1 |
| `Sources/GlassesSource.swift` | DAT session + raw `Stream` → UIImage, pause/resume, auto-restart, MockDeviceKit | G-1, G-2, G-8 |
| `Sources/PhoneCameraSource.swift` | AVCapture fallback camera | G-11 |
| `FrameEncoder.swift` | 5 fps throttle, downscale, JPEG, snap frames | G-3, G-9 |
| `CoreLink.swift` | `/stream` WebSocket, heartbeat, reconnect | G-8 |
| `AudioIO.swift` | HFP mic → 100 ms PCM chunks; reply queue with urgent interrupt; on-device voice | G-4, G-5 |
| `RelayModel.swift` | Wiring, spoken status cues, push-to-talk | G-6, G-7 |
| `ContentView.swift` | Hold-to-talk screen and settings | G-6 |

## Known gaps

- Not yet run on a real iPhone or real glasses. This Mac has no iOS Simulator runtime, so the app
  is only compile-checked (Simulator and device builds both pass).
- Running in the background with the screen locked is untested. The app keeps the screen awake
  while open, and the DAT sample stops its session when backgrounded.
- The glasses camera frame rate is requested at 15 fps (`.low`). If the SDK rejects it, try 24 in
  `GlassesSource.config`.
