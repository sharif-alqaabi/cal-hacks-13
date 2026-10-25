import MWDATCore
import Observation
import UIKit

/// Wires a frame source, the encoder, audio and the core socket together, and owns what the
/// screen shows. Everything the wearer needs to know is also spoken (PRD G-7).
@Observable
@MainActor
final class RelayModel {
  // MARK: Settings (persisted)

  var coreURL: String {
    didSet { UserDefaults.standard.set(coreURL, forKey: "coreURL") }
  }
  /// Glasses mic through the camera stream (experimental in Meta's SDK). Falls back to the phone
  /// mic on its own when no glasses audio is arriving.
  var glassesMic: Bool {
    didSet {
      UserDefaults.standard.set(glassesMic, forKey: "glassesMic")
      if glassesMic != oldValue && sourceKind == .glasses { switchSource() }
    }
  }
  var sourceKind: SourceKind {
    didSet {
      UserDefaults.standard.set(sourceKind.rawValue, forKey: "sourceKind")
      if sourceKind != oldValue { switchSource() }
    }
  }

  // MARK: Displayed state

  private(set) var linkState: CoreLink.State = .idle
  private(set) var sourceState: SourceState = .stopped
  private(set) var registration: RegistrationState
  private(set) var talking = false
  private(set) var lastReply = ""
  private(set) var framesPerSecond = 0
  private(set) var lastFrameSize = ""
  var errorMessage: String?

  var audioInputLabel: String { audio.inputLabel }
  var urgentLatencyMs: Int? { audio.lastUrgentLatencyMs }

  // MARK: Parts

  @ObservationIgnored private let link = CoreLink()
  @ObservationIgnored private let encoder = FrameEncoder()
  @ObservationIgnored private let audio = AudioIO()
  @ObservationIgnored private var source: FrameSource?
  @ObservationIgnored private var everConnected = false
  @ObservationIgnored private var framesThisSecond = 0
  @ObservationIgnored private var chunksThisTurn = 0
  @ObservationIgnored private var ticker: Task<Void, Never>?
  @ObservationIgnored private var registrationTask: Task<Void, Never>?
  @ObservationIgnored private var started = false

  init() {
    let defaults = UserDefaults.standard
    coreURL = defaults.string(forKey: "coreURL") ?? "ws://192.168.1.10:8000/stream"
    sourceKind = defaults.string(forKey: "sourceKind").flatMap(SourceKind.init(rawValue:)) ?? .glasses
    // Off by default: on glasses firmware 129 a stream with audio fails within seconds
    // (meta-wearables-dat-ios #356). Turn it on in Settings to try newer firmware.
    glassesMic = defaults.object(forKey: "glassesMic") as? Bool ?? false
    registration = Wearables.shared.registrationState
  }

  /// Called once when the screen appears.
  func start() {
    guard !started else { return }
    started = true
    UIApplication.shared.isIdleTimerDisabled = true

    link.onState = { [weak self] state in self?.linkChanged(state) }
    link.onMessage = { [weak self] msg in self?.handle(msg) }
    encoder.onFrame = { [weak self] frame, json in
      Task { @MainActor in self?.sendFrame(frame, json: json) }
    }
    audio.onChunk = { [weak self] chunk in
      self?.chunksThisTurn += 1
      self?.link.send(chunk)
    }

    registrationTask = Task { [weak self] in
      for await state in Wearables.shared.registrationStateStream() {
        guard let self else { return }
        relayLog("Meta AI registration: \(state)")
        let wasRegistered = self.registration == .registered
        self.registration = state
        if state == .registered && !wasRegistered && self.sourceKind == .glasses {
          self.switchSource()
        }
      }
    }
    MainThreadWatch.shared.start()
    ticker = Task { [weak self] in
      var seconds = 0
      while !Task.isCancelled {
        try? await Task.sleep(for: .seconds(1))
        guard let self else { return }
        MainThreadWatch.shared.beat()
        seconds += 1
        if seconds % 5 == 0 {
          relayLog("alive: \(self.framesThisSecond) fps, glasses audio buffers \(self.audio.glassesAudioBuffers()), link \(self.linkState)")
        }
        if (self.framesPerSecond == 0) != (self.framesThisSecond == 0) {
          relayLog(self.framesThisSecond == 0 ? "frames stopped" : "frames flowing, \(self.framesThisSecond) fps")
        }
        if self.framesPerSecond != self.framesThisSecond { self.framesPerSecond = self.framesThisSecond }
        self.framesThisSecond = 0
      }
    }

    audio.setGlassesAudio(sourceKind == .phoneCamera)
    Task { await audio.start() }
    connect()
    switchSource()
  }

  // MARK: - Actions

  func connect() {
    guard let url = Self.streamURL(from: coreURL) else {
      errorMessage = "Core address isn't a valid URL."
      return
    }
    everConnected = false
    link.connect(to: url)
  }

  func connectGlasses() {
    Task {
      relayLog("starting Meta AI registration")
      do { try await GlassesAccount.register() } catch {
        relayLog("registration failed: \(error)")
        errorMessage = "\(error)"
      }
    }
  }

  func openGlassesAppUpdate() {
    Task {
      relayLog("opening Meta AI: glasses app update")
      do { try await Wearables.shared.openDATGlassesAppUpdate() } catch {
        relayLog("glasses app update failed: \(error)")
        errorMessage = "\(error)"
      }
    }
  }

  func openFirmwareUpdate() {
    Task {
      relayLog("opening Meta AI: firmware update")
      do { try await Wearables.shared.openFirmwareUpdate() } catch {
        relayLog("firmware update failed: \(error)")
        errorMessage = "\(error)"
      }
    }
  }

  func disconnectGlasses() {
    Task {
      do { try await GlassesAccount.unregister() } catch { errorMessage = "\(error)" }
    }
  }

  /// Push-to-talk down (PRD G-6). Stops any reply in progress: the wearer is talking.
  func pttDown() {
    guard !talking else { return }
    guard link.isConnected else {
      audio.cue("Not connected.")
      return
    }
    talking = true
    UIImpactFeedbackGenerator(style: .medium).impactOccurred()
    audio.stopPlayback()
    link.send(PttMsg(state: "down"))
    chunksThisTurn = 0
    audio.beginCapture()
    relayLog("talk down (\(audio.inputLabel))")
  }

  func pttUp() {
    guard talking else { return }
    talking = false
    UIImpactFeedbackGenerator(style: .light).impactOccurred()
    audio.endCapture()  // flushes the last partial chunk before "up"
    link.send(PttMsg(state: "up"))
    relayLog("talk up, \(chunksThisTurn) audio chunks sent")
  }

  // MARK: - Wiring

  private func switchSource() {
    audio.setGlassesAudio(sourceKind == .phoneCamera)
    source?.stop()
    encoder.clear()
    let next: FrameSource
    switch sourceKind {
    case .glasses:
      let glasses = GlassesSource()
      glasses.wantsAudio = glassesMic
      let audio = self.audio
      glasses.onAudio = { buffer in audio.ingestGlassesAudio(buffer) }
      next = glasses
    #if DEBUG
    case .mockGlasses: next = GlassesSource(mock: true)
    #endif
    case .phoneCamera: next = PhoneCameraSource()
    }
    let encoder = self.encoder
    next.onImage = { image in encoder.submit(image) }
    next.onState = { [weak self] state in self?.sourceChanged(state) }
    source = next
    sourceState = .stopped
    next.start()
  }

  private func sendFrame(_ frame: FrameMsg, json: String) {
    // Privacy: nothing leaves the phone while the glasses are paused or off.
    guard sourceState == .streaming || frame.snap_id != nil else { return }
    link.sendText(json, isFrame: frame.snap_id == nil)
    framesThisSecond += 1
    // Only write observed state when it changes: each write redraws the screen.
    let size = "\(frame.w)×\(frame.h)"
    if size != lastFrameSize { lastFrameSize = size }
  }

  private func handle(_ msg: InboundMsg) {
    switch msg.type {
    case "say":
      if msg.urgent == true, talking { pttUp() }
      lastReply = msg.text ?? ""
      audio.play(msg)
    case "snap":
      if let id = msg.snap_id { encoder.snap(id) }
    default:
      break
    }
  }

  private func linkChanged(_ state: CoreLink.State) {
    let old = linkState
    linkState = state
    switch state {
    case .connected:
      audio.cue(everConnected ? "Reconnected." : "Connected.")
      everConnected = true
    case .reconnecting where old == .connected:
      if talking { pttUp() }
      audio.cue("Connection lost. Reconnecting.")
    default:
      break
    }
  }

  private func sourceChanged(_ state: SourceState) {
    let old = sourceState
    guard state != old else { return }
    relayLog("source \(sourceKind): \(state)")
    sourceState = state
    switch state {
    case .paused:
      encoder.clear()
      audio.cue("Paused.")
    case .streaming where old == .paused:
      audio.cue("Glasses resumed.")
    case .streaming where old != .streaming:
      audio.cue("Camera on.")
    case .waiting(let reason) where old == .streaming || old == .paused:
      encoder.clear()
      audio.cue(reason)
    case .failed:
      // Shown in the status line and logged. An alert here would pop up on every retry and take
      // the wearer's finger off the talk area.
      break
    default:
      break
    }
  }

  /// Accepts `ws://host:8000/stream`, `wss://…`, or a plain `http(s)://host:port` CORE_URL.
  static func streamURL(from text: String) -> URL? {
    var s = text.trimmingCharacters(in: .whitespacesAndNewlines)
    if s.hasPrefix("http://") { s = "ws://" + s.dropFirst(7) }
    if s.hasPrefix("https://") { s = "wss://" + s.dropFirst(8) }
    if !s.contains("://") { s = "ws://" + s }
    guard var components = URLComponents(string: s), components.host != nil else { return nil }
    if components.path.isEmpty || components.path == "/" { components.path = "/stream" }
    return components.url
  }
}

/// Logs from a background thread when the main thread stops answering, so a freeze shows up in
/// relay.log even though nothing on the main thread can log it.
final class MainThreadWatch: @unchecked Sendable {
  static let shared = MainThreadWatch()
  private let lock = NSLock()
  private var last = Date()
  private var reported = false
  private var timer: DispatchSourceTimer?

  func beat() {
    lock.lock()
    last = Date()
    if reported { relayLog("main thread responding again") }
    reported = false
    lock.unlock()
  }

  func start() {
    guard timer == nil else { return }
    let t = DispatchSource.makeTimerSource(queue: DispatchQueue.global(qos: .utility))
    t.schedule(deadline: .now() + 2, repeating: 1)
    t.setEventHandler { [weak self] in
      guard let self else { return }
      self.lock.lock()
      let stalled = Date().timeIntervalSince(self.last)
      let report = stalled > 3 && !self.reported
      if report { self.reported = true }
      self.lock.unlock()
      if report { relayLog("main thread blocked for \(Int(stalled)) s") }
    }
    t.resume()
    timer = t
  }
}
