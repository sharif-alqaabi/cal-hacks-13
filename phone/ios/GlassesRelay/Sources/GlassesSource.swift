import AVFoundation
import MWDATCamera
import MWDATCore
import UIKit

#if DEBUG
import MWDATMockDevice
#endif

/// Meta glasses camera through the Wearables Device Access Toolkit: a `DeviceSession` on the
/// auto-selected glasses, plus a raw-codec `Stream` whose frames convert straight to UIImage.
/// Restarts itself when the glasses come back after being folded, removed or disconnected.
@MainActor
final class GlassesSource: FrameSource {
  var onImage: (@Sendable (UIImage) -> Void)?
  var onState: ((SourceState) -> Void)?
  /// The glasses mic, delivered inside the camera stream (no Bluetooth headset link). Called on
  /// the SDK's thread with 16 kHz mono PCM.
  var onAudio: (@Sendable (AVAudioPCMBuffer) -> Void)?
  /// Ask for in-stream audio. Turned off for the rest of the run if a stream with audio fails
  /// (on firmware 129 it can end the video too, meta-wearables-dat-ios #356).
  var wantsAudio = false
  private var audioFailed = false
  private var streamHasAudio = false
  /// A camera is being set up (permission checks are async); stops a second one starting.
  private var addingCamera = false
  private var recentRestarts: [Date] = []

  private let wearables: WearablesInterface = Wearables.shared
  private let selector: AutoDeviceSelector
  private let mock: Bool
  private var session: DeviceSession?
  private var camera: MWDATCamera.Camera?
  private let sessionTokens = ListenerTokenBag()
  private let streamTokens = ListenerTokenBag()
  private var deviceMonitor: Task<Void, Never>?
  private var retry: Task<Void, Never>?
  private var wanted = false
  /// The glasses refused the session until their app is updated in Meta AI; retry slowly meanwhile.
  private var updateRequired = false
  private let lastFrame = FrameClock()
  private var watchdog: Task<Void, Never>?

  /// Core's hazard loop runs at 15 fps (contracts/CONTRACTS.md), so ask for exactly that at low resolution.
  private static let config = StreamConfiguration(videoCodec: .raw, resolution: .low, frameRate: 15)
  private static let configWithAudio = StreamConfiguration(
    videoCodec: .raw, audioCodec: .pcm(sampleRate: .rate16000, numberOfChannels: 1), resolution: .low, frameRate: 15)

  init(mock: Bool = false) {
    self.mock = mock
    selector = AutoDeviceSelector(wearables: wearables)
  }

  func start() {
    wanted = true
    #if DEBUG
    if mock {
      MockRig.ensurePaired()
    } else if MockRig.used {
      // MockDeviceKit replaced the real device list for this run; turning it off doesn't bring it back.
      onState?(.failed("Restart the app to use your real glasses after Mock glasses."))
      return
    }
    #endif
    if deviceMonitor == nil {
      deviceMonitor = Task { [weak self] in
        guard let self else { return }
        for await device in self.selector.activeDeviceStream() {
          if let id = device, let d = self.wearables.deviceForIdentifier(id) {
            relayLog("glasses: active device \(d.name) \(d.deviceType()) link=\(d.linkState) compatibility=\(d.compatibility())")
          } else {
            relayLog("glasses: active device \(device.map { "\($0)" } ?? "none")")
          }
          if device != nil {
            self.startSessionIfNeeded()
          } else if self.session == nil, self.wanted {
            self.onState?(.waiting("Put on your glasses."))
          }
        }
      }
    }
    startSessionIfNeeded()
  }

  func stop() {
    wanted = false
    watchdog?.cancel()
    watchdog = nil
    retry?.cancel()
    deviceMonitor?.cancel()
    deviceMonitor = nil
    camera?.stop()
    session?.stop()
    cleanupSession()
    #if DEBUG
    // Otherwise the simulated pair stays the "active device" and Glasses mode streams the mock.
    if mock { MockRig.tearDown() }
    #endif
    onState?(.stopped)
  }

  // MARK: - Session

  private func startSessionIfNeeded() {
    guard wanted, session == nil else { return }
    guard wearables.registrationState == .registered else {
      relayLog("glasses: not registered (\(wearables.registrationState))")
      onState?(.waiting("Connect your glasses in Settings."))
      return
    }
    do {
      let s = try wearables.createSession(deviceSelector: selector)
      session = s
      // Subscribe before start() so no state transition is missed.
      s.statePublisher.listen { [weak self] state in
        Task { @MainActor in self?.sessionChanged(state) }
      }.store(in: sessionTokens)
      s.errorPublisher.listen { [weak self] error in
        Task { @MainActor in self?.sessionFailed(error) }
      }.store(in: sessionTokens)
      relayLog("glasses: starting session")
      onState?(.starting)
      try s.start()
    } catch {
      relayLog("glasses: session start threw \(error)")
      cleanupSession()
      onState?(.failed(error.localizedDescription))
      scheduleRetry()
    }
  }

  private func sessionFailed(_ error: DeviceSessionError) {
    relayLog("glasses: session error \(error)")
    switch error {
    case .datAppOnTheGlassesUpdateRequired, .insufficientSDKVersion:
      updateRequired = true
      onState?(.failed("Update the app on your glasses: Settings > Update app on glasses."))
    default:
      onState?(.failed(error.localizedDescription))
    }
  }

  private func sessionChanged(_ state: DeviceSessionState) {
    relayLog("glasses: session \(state)")
    switch state {
    case .started:
      updateRequired = false
      // Also the resume after a pause; startStream() is a no-op while a stream exists.
      Task { await startStream() }
    case .paused:
      onState?(.paused)
    case .stopped:
      cleanupSession()
      if wanted {
        if !updateRequired { onState?(.waiting("Glasses disconnected.")) }
        scheduleRetry()
      }
    case .idle, .starting, .stopping:
      break
    }
  }

  private func scheduleRetry() {
    retry?.cancel()
    retry = Task { [weak self] in
      try? await Task.sleep(for: .seconds(self?.updateRequired == true ? 10 : 2))
      guard !Task.isCancelled else { return }
      self?.startSessionIfNeeded()
    }
  }

  private func cleanupSession() {
    streamTokens.clear()
    sessionTokens.clear()
    camera = nil
    session = nil
  }

  // MARK: - Stream

  private func startStream() async {
    guard let s = session, s.state == .started, camera == nil, !addingCamera else { return }
    addingCamera = true
    defer { addingCamera = false }
    do {
      let permission = try await wearables.checkPermissionStatus(.camera)
      relayLog("glasses: camera permission \(permission)")
      if permission != .granted {
        // Opens the Meta AI app; resumes when the wearer comes back.
        onState?(.waiting("Allow camera access in the Meta AI app."))
        guard try await wearables.requestPermission(.camera) == .granted else {
          onState?(.failed("Glasses camera permission denied."))
          return
        }
      }
      var withAudio = wantsAudio && !audioFailed && !mock
      if withAudio {
        let mic = try await wearables.checkPermissionStatus(.microphone)
        relayLog("glasses: microphone permission \(mic)")
        if mic != .granted {
          onState?(.waiting("Allow microphone access in the Meta AI app."))
          withAudio = try await wearables.requestPermission(.microphone) == .granted
          if !withAudio { relayLog("glasses: microphone denied, using the phone mic") }
        }
      }
      guard session === s, s.state == .started, camera == nil else { return }
      guard let cam = try s.addCamera(config: withAudio ? Self.configWithAudio : Self.config) else {
        onState?(.failed("Couldn't open the glasses camera."))
        return
      }
      camera = cam
      let onImage = self.onImage
      cam.stream.statePublisher.listen { [weak self] state in
        Task { @MainActor in self?.streamChanged(state) }
      }.store(in: streamTokens)
      let lastFrame = self.lastFrame
      cam.stream.videoFramePublisher.listen { frame in
        lastFrame.touch()
        if let image = frame.makeUIImage() { onImage?(image) }
      }.store(in: streamTokens)
      streamHasAudio = withAudio
      if withAudio, let onAudio = self.onAudio {
        cam.stream.audioFramePublisher.listen { frame in onAudio(frame.pcmBuffer) }.store(in: streamTokens)
      }
      cam.stream.errorPublisher.listen { [weak self] error in
        relayLog("glasses: stream error \(error)")
        // videoStreamingError ends the stream without a state change; start a new one.
        Task { @MainActor in self?.restartCamera("stream error") }
      }.store(in: streamTokens)
      relayLog("glasses: camera \(withAudio ? "with" : "without") glasses mic")
      relayLog("glasses: starting camera stream")
      cam.stream.start()
    } catch {
      relayLog("glasses: camera setup threw \(error)")
      onState?(.failed(error.localizedDescription))
    }
  }

  /// Drops the camera and adds a fresh one on the same session, which is how the stream recovers
  /// from `videoStreamingError` and from silent stalls (meta-wearables-dat-ios #276).
  private func restartCamera(_ reason: String) {
    guard wanted, camera != nil else { return }
    if streamHasAudio && !audioFailed {
      // The stream that failed carried audio: keep the video and drop the audio from now on.
      audioFailed = true
      relayLog("glasses: in-stream audio off for this run; the phone mic takes over")
    }
    let now = Date()
    recentRestarts = recentRestarts.filter { now.timeIntervalSince($0) < 15 } + [now]
    onState?(.starting)
    streamTokens.clear()
    camera?.stop()
    camera = nil
    if recentRestarts.count >= 3 {
      // New cameras on this session keep failing: the glasses need a fresh session.
      relayLog("glasses: \(recentRestarts.count) camera restarts in 15 s, restarting the session (\(reason))")
      recentRestarts.removeAll()
      session?.stop()   // its .stopped state cleans up and schedules a new session
      return
    }
    relayLog("glasses: restarting camera (\(reason))")
    Task {
      try? await Task.sleep(for: .seconds(1))
      await startStream()
    }
  }

  /// "streaming" doesn't promise frames: restart if none arrive for 5 s.
  private func startWatchdog() {
    guard watchdog == nil else { return }
    watchdog = Task { [weak self] in
      while !Task.isCancelled {
        try? await Task.sleep(for: .seconds(2))
        guard let self, self.wanted else { return }
        if self.camera != nil, self.streaming, self.lastFrame.age > 5 {
          self.restartCamera("no frames for 5 s")
        }
      }
    }
  }

  private var streaming = false

  private func streamChanged(_ state: StreamState) {
    relayLog("glasses: stream \(state)")
    streaming = state == .streaming
    switch state {
    case .streaming:
      lastFrame.touch()
      startWatchdog()
      onState?(.streaming)
    case .paused: onState?(.paused)
    case .waitingForDevice: onState?(.waiting("Put on your glasses."))
    case .starting: onState?(.starting)
    case .stopped:
      // The stream can end on its own (thermal, battery, error) while the session lives on.
      streamTokens.clear()
      camera?.stop()
      camera = nil
      if wanted, session?.state == .started {
        Task {
          try? await Task.sleep(for: .seconds(1))
          await startStream()
        }
      }
    case .stopping: break
    }
  }
}

/// When the last glasses frame arrived; written from the SDK's frame callback.
private final class FrameClock: @unchecked Sendable {
  private let lock = NSLock()
  private var last = CACurrentMediaTime()

  func touch() {
    lock.lock()
    last = CACurrentMediaTime()
    lock.unlock()
  }

  var age: CFTimeInterval {
    lock.lock()
    defer { lock.unlock() }
    return CACurrentMediaTime() - last
  }
}

/// Registration with the Meta AI app (PRD G-1). Survives app restarts on its own.
enum GlassesAccount {
  static func register() async throws { try await Wearables.shared.startRegistration() }
  static func unregister() async throws { try await Wearables.shared.startUnregistration() }
}

#if DEBUG
/// Simulated glasses from MockDeviceKit, worn and streaming. Uses a bundled `mock_feed.mp4`
/// when present, otherwise the phone's back camera.
@MainActor
enum MockRig {
  private static var glasses: (any MockGlasses)?
  /// Set once MockDeviceKit has been enabled in this run.
  private(set) static var used = false

  static func ensurePaired() {
    guard glasses == nil else { return }
    used = true
    MockDeviceKit.shared.enable(config: MockDeviceKitConfig(initiallyRegistered: true, initialPermissionsGranted: true))
    do {
      let g = try MockDeviceKit.shared.pairGlasses(model: .rayBanMeta)
      g.powerOn()
      g.unfold()
      g.don()
      // The kit refuses (fatally) to stream from mock glasses with no camera feed.
      if let clip = Bundle.main.url(forResource: "mock_feed", withExtension: "mp4") {
        g.services.camera.setCameraFeed(fileURL: clip)
      } else {
        g.services.camera.setCameraFeed(cameraFacing: .back)
      }
      glasses = g
    } catch {
      relayLog("mock glasses failed: \(error)")
    }
  }

  static func tearDown() {
    guard glasses != nil else { return }
    MockDeviceKit.shared.disable()
    glasses = nil
  }
}
#endif
