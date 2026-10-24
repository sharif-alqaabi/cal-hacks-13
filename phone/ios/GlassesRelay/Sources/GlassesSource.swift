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

  /// Bluetooth bandwidth is the limit; core only needs ~5 fps, so ask for little.
  private static let config = StreamConfiguration(videoCodec: .raw, resolution: .low, frameRate: 15)

  init(mock: Bool = false) {
    self.mock = mock
    selector = AutoDeviceSelector(wearables: wearables)
  }

  func start() {
    wanted = true
    #if DEBUG
    if mock { MockRig.ensurePaired() }
    #endif
    if deviceMonitor == nil {
      deviceMonitor = Task { [weak self] in
        guard let self else { return }
        for await device in self.selector.activeDeviceStream() {
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
    retry?.cancel()
    deviceMonitor?.cancel()
    deviceMonitor = nil
    camera?.stop()
    session?.stop()
    cleanupSession()
    onState?(.stopped)
  }

  // MARK: - Session

  private func startSessionIfNeeded() {
    guard wanted, session == nil else { return }
    guard wearables.registrationState == .registered else {
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
        Task { @MainActor in self?.onState?(.failed(error.localizedDescription)) }
      }.store(in: sessionTokens)
      onState?(.starting)
      try s.start()
    } catch {
      cleanupSession()
      onState?(.failed(error.localizedDescription))
      scheduleRetry()
    }
  }

  private func sessionChanged(_ state: DeviceSessionState) {
    switch state {
    case .started:
      // Also the resume after a pause; startStream() is a no-op while a stream exists.
      Task { await startStream() }
    case .paused:
      onState?(.paused)
    case .stopped:
      cleanupSession()
      if wanted {
        onState?(.waiting("Glasses disconnected."))
        scheduleRetry()
      }
    case .idle, .starting, .stopping:
      break
    }
  }

  private func scheduleRetry() {
    retry?.cancel()
    retry = Task { [weak self] in
      try? await Task.sleep(for: .seconds(2))
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
    guard let s = session, s.state == .started, camera == nil else { return }
    do {
      if try await wearables.checkPermissionStatus(.camera) != .granted {
        // Opens the Meta AI app; resumes when the wearer comes back.
        onState?(.waiting("Allow camera access in the Meta AI app."))
        guard try await wearables.requestPermission(.camera) == .granted else {
          onState?(.failed("Glasses camera permission denied."))
          return
        }
      }
      guard session === s, s.state == .started, camera == nil else { return }
      guard let cam = try s.addCamera(config: Self.config) else {
        onState?(.failed("Couldn't open the glasses camera."))
        return
      }
      camera = cam
      let onImage = self.onImage
      cam.stream.statePublisher.listen { [weak self] state in
        Task { @MainActor in self?.streamChanged(state) }
      }.store(in: streamTokens)
      cam.stream.videoFramePublisher.listen { frame in
        if let image = frame.makeUIImage() { onImage?(image) }
      }.store(in: streamTokens)
      cam.stream.errorPublisher.listen { [weak self] error in
        Task { @MainActor in self?.onState?(.failed(error.localizedDescription)) }
      }.store(in: streamTokens)
      cam.stream.start()
    } catch {
      onState?(.failed(error.localizedDescription))
    }
  }

  private func streamChanged(_ state: StreamState) {
    switch state {
    case .streaming: onState?(.streaming)
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

  static func ensurePaired() {
    guard glasses == nil else { return }
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
      NSLog("[Relay] mock glasses failed: \(error)")
    }
  }
}
#endif
