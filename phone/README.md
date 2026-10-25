# phone: glasses & phone relay (part 1)

An iPhone app that turns Meta Ray-Ban glasses into core's camera (PRD 1). It streams ~15 fps JPEG
frames from the glasses and push-to-talk audio to `ws://<laptop>:8000/stream`, and plays every `say`
from core. While the glasses camera streams, voice uses the phone's mic and speaker (see *Audio*). Message shapes are core's: [`core/contracts/CONTRACTS.md`](../core/contracts/CONTRACTS.md).

## Build and install

Needs Xcode 26+ and XcodeGen (`brew install xcodegen`).

```bash
cd phone/ios
./setup.sh                 # creates Config.xcconfig from the example, generates GlassesRelay.xcodeproj
open GlassesRelay.xcodeproj
```

1. In `Config.xcconfig` set `DEVELOPMENT_TEAM` (Xcode > Settings > Accounts) and a unique `RELAY_BUNDLE_ID`.
2. **Signing:** a free personal Apple team cannot sign the Hotspot Configuration and Wi-Fi Info
   entitlements in `GlassesRelay.entitlements`. Set
   `RELAY_ENTITLEMENTS = GlassesRelay/GlassesRelay-free.entitlements` and rerun `./setup.sh`.
   That is enough: the app streams over Bluetooth Classic (see *Transport*), which needs no paid team.
3. Keep `META_APP_ID = 0` and `CLIENT_TOKEN = 0` (as in Meta's samples) while Developer Mode is on.
4. **Developer Mode has two parts**, and the glasses refuse every session with
   `datAppOnTheGlassesUpdateRequired` until both are done, in this order:
   1. In Meta AI: **Settings > App Info**, tap the app version 5 times, turn on **Developer Mode**.
   2. On the same screen, with the glasses worn and unfolded, press **Install** for the glasses and wait
      until every stage finishes (this puts the developer runtime on the glasses).
   3. Then run the app from Xcode and tap **Settings > Connect glasses** to register. The camera
      permission prompt opens Meta AI the first time the stream starts.
5. **If sessions still fail with "update required"** (what fixed it for us, from Meta issue #292):
   *Disconnect glasses* in the app, turn Developer Mode off, close the glasses in their case for
   30 s, restart the iPhone, turn Developer Mode on again while wearing them and press Install,
   then *Connect glasses* again. The order matters: register after the runtime is installed.

Check first that your glasses model and firmware are supported:
https://wearables.developer.meta.com/docs/develop/dat/version-dependencies/

## Using it

- The whole screen is one **hold-to-talk** area. VoiceOver passes touches straight through
  (`allowsDirectInteraction`), so you hold it with one finger; no double-tap needed.
- Spoken cues: "Connected", "Connection lost. Reconnecting.", "Reconnected", "Paused",
  "Glasses resumed", "Camera on", "Not connected" (talking while offline).
- The **Settings** sheet holds the core address, camera source, the glasses-mic switch, glasses
  registration, and *Update app on glasses* / *Update glasses software* (open Meta AI).
- **Camera source:**
  - *Glasses camera* is the default.
  - *Phone camera (fallback)* is PRD G-11: switch in one tap, with no backend change.
  - *Mock glasses* uses Meta's MockDeviceKit and only appears in Debug builds.
- The core address takes `ws://host:8000/stream`, `wss://tunnel/stream` or plain `http://host:8000`.

## Behaviour that matters to core

| What | How |
|---|---|
| Frames | Long side ≤ 640 px at JPEG q0.5, capped at 15 fps (core's hazard rate). Glasses frames are portrait 9:16 (e.g. 360×640), so read `w`/`h`. |
| Back-pressure | At most 2 frames in flight, and no frames while the heartbeat round trip is over 350 ms (pings queue behind frames, so that means the send buffer is backing up). Frames are dropped, never queued. Over venue wifi shared with the glasses' Bluetooth this gives ~10–12 fps with frames reaching core in < 200 ms. |
| `ts` | Unix seconds (float), as in `contracts/stream.py`. |
| Audio | 16-bit mono, 16 kHz, 100 ms chunks, only while the button is held. The last partial chunk is sent before `ptt up`. Glasses camera: phone mic (or the glasses' in-stream mic when switched on). Phone camera: glasses mic over HFP (8 kHz). |
| `say` | Non-urgent replies are queued and played in order. Urgent replies clear the queue and interrupt. An empty `pcm16_b64` is read out with the on-device voice. Pressing talk stops playback (barge-in). |
| `snap` | Answered with the latest frame at long side ≤ 1280 px, carrying `snap_id`. |
| Pause | Glasses tapped, removed or folded means nothing is sent, and the held frame is dropped. Frames are never written to disk. |
| Reconnect | Ping every 1 s; no pong for 3 s counts as a drop. Retries at 0.5 s, 1 s, then every 2 s. |

## Transport

The SDK picks the link from `Info.plist` (Meta, issue #276 and #354): Wi-Fi when it declares
`NSLocalNetworkUsageDescription` plus a non-empty `NSBonjourServices`, Bluetooth Classic when it declares
the `external-accessory` background mode and `UISupportedExternalAccessoryProtocols = com.meta.ar.wearable`
(Classic wins when both are present). Wi-Fi needs the paid-team entitlements; Classic doesn't. This app
declares Classic and no Bonjour services. Classic has less bandwidth (fine at `.low`, 15 fps) and is for
development only: shipping it needs MFi. `NSLocalNetworkUsageDescription` stays, for the laptop on the LAN.

## Audio

Tested on Ray-Ban Meta (Wayfarer), firmware 129.0.1.23.378, SDK 1.0.1:

- **While the glasses camera streams, the glasses mute app audio** (Meta issues #358, #256), and using
  them as a Bluetooth headset (HFP) at the same time broke the audio engine and added seconds of lag.
  So with the glasses camera the app uses the **phone's mic and speaker**: wear the phone in a chest
  pocket or on a lanyard. With the phone camera it uses the glasses over HFP as before.
- **Glasses mic** (Settings switch, off by default) carries the mic inside the camera stream
  (`audioCodec: .pcm 16 kHz`). Audio arrives, but on firmware 129 the video stream ends with
  `videoStreamingError` about 4 s later (Meta issue #356). The app then drops the audio for the rest
  of the run, and a turn uses the phone mic whenever no glasses audio arrived in the last second.

## Recovery

- No frames for 5 s, or a stream error: the camera is restarted on the same session. Three restarts in
  15 s: the whole session is restarted (a stuck stream needed that).
- The audio engine is rebuilt only when the route changes, and recreated if iOS's media services reset.
  On a talk press with a silent mic it is rebuilt before listening.

## Logs

`relay.log` (in the app's Documents) records each glasses, stream, audio and talk step, a heartbeat
every 5 s and main-thread stalls. Read it over the cable without Xcode:

```bash
xcrun devicectl device copy from --device <udid> --domain-type appDataContainer \
  --domain-identifier <bundle id> --source Documents/relay.log --destination relay.log
```

Meta's own SDK log is at `Library/Caches/MetaWearablesDAT/Logs/MetaWearablesDAT.log` in the same container.

## Testing without the phone

`GlassesRelay/CoreLink.swift` and `Messages.swift` are Foundation-only. They were exercised on a Mac
against `python -m tests.run_offline --with-stubs` (core with faked APIs) using the core fixtures:

- **Chair walk:** urgent "Chair coming up ahead" twice, 3 s apart.
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
| `FrameEncoder.swift` | 15 fps throttle, downscale, JPEG, snap frames | G-3, G-9 |
| `CoreLink.swift` | `/stream` WebSocket, heartbeat, reconnect, congestion drop | G-8 |
| `AudioIO.swift` | Phone / glasses mic → 100 ms PCM chunks; reply queue with urgent interrupt; on-device voice | G-4, G-5 |
| `Log.swift` | `relay.log` file logger | |
| `RelayModel.swift` | Wiring, spoken status cues, push-to-talk | G-6, G-7 |
| `ContentView.swift` | Hold-to-talk screen and settings | G-6 |

## Known gaps

- Run on an iPhone 16 Pro Max with Ray-Ban Meta (Wayfarer), firmware 129: glasses frames reach core at
  10–12 fps within ~200 ms, and push-to-talk turns ("What's in front of me?") get their first audio
  ~1.5 s after release.
- Replies play from the phone speaker while the glasses camera streams (glasses mute app audio).
- Running in the background with the screen locked is untested. The app keeps the screen awake
  while open.
- On SDK 1.0.x a Bluetooth Classic stream's memory grows over time (Meta issue #324): restart the
  app between long runs.
- `tools/recorder.py` and the Mac harness predate tonight's changes; the harness now also needs `Log.swift`.
