## PRD 1 — Glasses & Phone Relay

Oct 23, 2026 · @Marvin

## Summary

The phone relay turns Meta Ray-Ban glasses into a hands-free camera, microphone and speaker for our backend. At judging it must stream the wearer's view to core and play every reply through the glasses, live, for the full two-hour window without a restart.

Owner: Engineer 1 · Part of: Cal Hacks 13.0 — Assistive Glasses Team Plan · Primary user: blind

and low-vision adults who work (pending the team's community decision).

## Goals

- Live frames from the glasses reach core at ~5 fps.

- Glasses mic in, spoken replies out through the glasses speakers, with urgent warnings jumping the queue.

- Recorded fixtures so engineers 2–4 never need the hardware.

## Non-goals

- Drawing anything on a Meta Ray-Ban Display HUD.

- On-device inference or offline mode.

- App store distribution, accounts, or any UI beyond connect, push-to-talk and status.

## Users & stories

| As a… I want to… So that… Wearer start the assistant with one tap, then my hands stay free for my cane leave the phone in my pocket and my work Wearer use the phone app entirely with I never need sighted help to VoiceOver or TalkBack operate it Wearer hold one large push-to-talk area it only listens when I mean it to while I speak |
| --- |


| As a… | I want to… | So that… |
| --- | --- | --- |
| Wearer | hear urgent warnings immediately, | I can stop before I hit something |
|   | even mid-sentence |   |
| Wearer | hear when the connection drops or | I never trust a silent assistant |
|   | recovers |   |
| Teammate (Eng | replay real glasses footage on | I can build and test without the |
| 2–4) | demand | glasses |
| Judge | see that the frames really come from | the demo is credible |
|   | the glasses |   |

## Requirements

Eleven functional requirements; G-1 to G-6, G-10 and G-11 are P0 and must pass before the Saturday 6 PM freeze.

| ID | Requirement | Priority Acceptance criteria |
| --- | --- | --- |
| G-1 Register the app with the Meta AI |   | P0 First-run flow completes on our |
|   | app and request camera permission | glasses; permission survives an app |
|   |   | restart |
| G-2 Start a toolkit session and stream |   | P0 Core receives ≥ 4 fps at 640×480 |
|   | camera frames | for 10 continuous minutes |
| G-3 Downscale and JPEG-encode |   | P0 Every message validates against |
|   | frames, send as frame messages | contracts/ ; quality ~70 |
| G-4 Capture the glasses mic over |   | P0 Core transcribes 4 of 5 scripted |
|   | Hands-Free Profile and send audio | phrases correctly in a quiet room |
|   | messages |   |
| G-5 Play say audio through the glasses |   | P0 An urgent reply starts within 300 |
|   | speakers; urgent interrupts | ms of arrival (target) and cuts off |
|   | current playback | normal speech |
| G-6 Full-screen push-to-talk area, |   | P0 A teammate operates it eyes- |
|   | labelled for VoiceOver and TalkBack | closed; sends ptt down and up |


| ID | Requirement | Priority Acceptance criteria |
| --- | --- | --- |
| G-7 Spoken status cues: connected, |   | P1 Each state change is announced |
|   | reconnecting, paused | within 2 s |
| G-8 Auto-reconnect the WebSocket; |   | P1 Recovers within 5 s with no action |
|   | resume after the glasses are | beyond putting the glasses back on |
|   | tapped, removed or folded |   |
| G-9 Answer a snap with one full- |   | P1 Reply arrives within 1 s (target) |
|   | resolution frame carrying its |   |
|   | snap_id |   |
| G- | Fixtures and replay.py for the | P0 5–10 minutes covering every demo |
| 10 | team | beat; replay.py streams it in real |
|   |   | time to any CORE_URL |
| G-11 Fallback camera (phone camera or |   | P0 Switching takes under a minute and |
|   | webcam) behind one switch | needs no backend change |

## Non-functional

- Endurance: runs the 2-hour judging window on a power bank without a restart.

- Privacy: no frames are stored on the phone; nothing streams while the session is paused.

- Network: works on venue wifi; never uses a personal hotspot (banned at the venue).

- Accessibility: every control has a spoken label; no information is shown only visually.

## Interfaces & dependencies

The relay speaks one contract, the /stream WebSocket to core, defined in the plan's Async split & contracts tab.

| Direction | Message Notes |   |
| --- | --- | --- |
| Phone → core | frame | {ts, jpeg_b64, w, h, snap_id} , ~5 fps |
| Phone → core | audio | {ts, pcm16_b64, rate: 8000} |
| Phone → core | ptt | {state: "down" or "up"} |
| Core → phone | say | {id, text, pcm16_b64, rate, urgent} |


| Direction | Message Notes |   |
| --- | --- | --- |
| Core → phone | snap | {snap_id} ; answer with one full-resolution frame |

## Meta Wearables Device Access Toolkit facts that shape the design

- Developer preview, with SDKs for iOS (Swift Package) and Android (Gradle via GitHub Packages, which needs a GitHub token).

- Video streams over Bluetooth at up to 720p / 30 fps and drops automatically when bandwidth is limited.

- Mic input uses Hands-Free Profile at 8 kHz mono; speaker output goes through normal Bluetooth audio.

- One session runs at a time; tapping, removing or folding the glasses pauses it.

- Registration and camera permission deeplink through the Meta AI app.

- MockDeviceKit simulates glasses for testing without hardware.

## Dependencies and mocks

| Needs | Owner | Mock until ready |
| --- | --- | --- |
| Core /stream server | Eng 2 | Local server that logs messages and sends a |
|   |   | canned say and snap |
| Glasses pairing | Hardware MockDeviceKit |   |
| Meta developer | Engineer | None; do it first |
| registration | 1 |   |

## Acceptance, milestones & risks

The relay is done when the wearer can run the whole demo eyes-closed, touching the phone only for push-to-talk.

| Metric | Target | Measured by |
| --- | --- | --- |
| Frame rate at core | ≥ 4 fps sustained Core frame log |   |
| Glasses-to-core delay | < 500 ms | ts vs. core receive time (sync |
|   |   | phone and laptop clocks) |


| Metric | Target | Measured by |
| --- | --- | --- |
| Urgent playback start | < 300 ms after | Phone log |
|   | arrival |   |
| Unplanned disconnects in a 10- | 0 | Phone log |
| minute run |   |   |

## Demo acceptance test

- 1. Start the app with VoiceOver or TalkBack on, eyes closed; hear "connected".

- 2. Walk the demo path; the chair warning plays through the glasses.

- 3. Hold push-to-talk for each scripted question; every reply plays through the glasses.

- 4. Take the glasses off and put them back on; the session resumes with a spoken cue.

## Milestones

- 1. Fri 11 PM: fixtures and replay.py posted.

- 2. Fri 12 AM gate: live frames reach core, or the fallback camera is chosen.

- 3. Sat 10 AM: audio in, say out, push-to-talk, snap .

- 4. Sat 6 PM: reconnect and spoken status cues; feature freeze.

- 5. Sun 10:30 AM: Engineer 1 wears the glasses for judging.

| Risk | Mitigation |
| --- | --- |
| Glasses firmware or Meta AI app version | Check Version Dependencies first; |
| not supported | MockDeviceKit; fallback camera |
| Bluetooth bandwidth lowers resolution | Design for 480p; use snap for describe and |
|   | recall |
| 8 kHz mic misheard by speech-to-text | Short commands; phone-mic switch |
| iOS on-device install needs code signing | Set up Xcode signing with a personal team |
|   | before anything else |

## Open questions

- iOS or Android?

- Which glasses model and firmware do we have?

- Push-to-talk on screen only, or also voice activity?


## [Source: Meta Wearables integration overview](https://wearables.developer.meta.com/docs/develop/dat/build-overview/)
