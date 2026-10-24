import AVFoundation
import QuartzCore

/// Both audio directions on one AVAudioEngine.
/// - In: the glasses mic over Bluetooth HFP (8 kHz; the phone mic at 16 kHz when no glasses
///   are connected), sent as 100 ms `audio` chunks only between `beginCapture` and `endCapture`.
/// - Out: `say` replies and status cues, played in order; an urgent reply clears the queue and
///   cuts off whatever is playing. A `say` with no audio is read out with the on-device voice.
/// With the glasses connected, the HFP route plays everything through their speakers.
@MainActor
final class AudioIO: NSObject {
  /// Called on the main actor with each 100 ms chunk while capturing.
  var onChunk: ((AudioMsg) -> Void)?
  private(set) var inputLabel = "no mic"
  private(set) var lastUrgentLatencyMs: Int?

  private let engine = AVAudioEngine()
  private let player = AVAudioPlayerNode()
  private let synth = AVSpeechSynthesizer()
  private let capture = Capture()
  private let playFormat = AVAudioFormat(standardFormatWithSampleRate: 24000, channels: 1)!

  private enum Clip {
    case pcm(AVAudioPCMBuffer)
    case speech(String)
  }
  private var queue: [Clip] = []
  private var playing = false
  private var token = 0
  private var currentUtterance: ObjectIdentifier?
  private var started = false

  override init() {
    super.init()
    synth.delegate = self
    capture.onChunk = { [weak self] data, rate in
      let msg = AudioMsg(ts: Clock.now, pcm16_b64: data.base64EncodedString(), rate: rate)
      Task { @MainActor in self?.onChunk?(msg) }
    }
  }

  func start() async {
    guard !started else { return }
    started = true
    let micAllowed = await AVAudioApplication.requestRecordPermission()
    engine.attach(player)
    engine.connect(player, to: engine.mainMixerNode, format: playFormat)
    rebuild(micAllowed: micAllowed)
    let center = NotificationCenter.default
    center.addObserver(forName: AVAudioSession.routeChangeNotification, object: nil, queue: .main) { [weak self] _ in
      Task { @MainActor in self?.routeChanged() }
    }
    center.addObserver(forName: .AVAudioEngineConfigurationChange, object: engine, queue: .main) { [weak self] _ in
      Task { @MainActor in self?.rebuild(micAllowed: AVAudioApplication.shared.recordPermission == .granted) }
    }
  }

  // MARK: - Capture (push-to-talk)

  func beginCapture() { capture.begin() }
  func endCapture() { capture.end() }

  // MARK: - Playback

  func play(_ say: InboundMsg) {
    let arrived = CACurrentMediaTime()
    let clip: Clip
    if let b64 = say.pcm16_b64, !b64.isEmpty, let data = Data(base64Encoded: b64),
      let buffer = Self.makeBuffer(pcm16: data, rate: Double(say.rate ?? 24000), to: playFormat)
    {
      clip = .pcm(buffer)
    } else if let text = say.text, !text.isEmpty {
      clip = .speech(text)
    } else {
      return
    }
    if say.urgent == true {
      stopPlayback()
      queue = [clip]
      playNext()
      lastUrgentLatencyMs = Int((CACurrentMediaTime() - arrived) * 1000)
      NSLog("[Relay] urgent say \(say.id ?? "?") started \(lastUrgentLatencyMs ?? -1) ms after arrival")
    } else {
      queue.append(clip)
      if !playing { playNext() }
    }
  }

  /// Short status cue ("Connected"), queued like a normal reply.
  func cue(_ text: String) {
    queue.append(.speech(text))
    if !playing { playNext() }
  }

  /// Stops speech and drops everything queued (used for urgent replies and push-to-talk).
  func stopPlayback() {
    token += 1
    queue.removeAll()
    player.stop()
    currentUtterance = nil
    if synth.isSpeaking { synth.stopSpeaking(at: .immediate) }
    playing = false
  }

  private func playNext() {
    guard !queue.isEmpty else {
      playing = false
      return
    }
    playing = true
    token += 1
    let t = token
    switch queue.removeFirst() {
    case .pcm(let buffer):
      ensureRunning()
      player.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { [weak self] _ in
        Task { @MainActor in
          guard let self, t == self.token else { return }
          self.playNext()
        }
      }
      if !player.isPlaying { player.play() }
    case .speech(let text):
      let utterance = AVSpeechUtterance(string: text)
      currentUtterance = ObjectIdentifier(utterance)
      synth.speak(utterance)
    }
  }

  fileprivate func utteranceFinished(_ id: ObjectIdentifier) {
    guard id == currentUtterance else { return }
    currentUtterance = nil
    playNext()
  }

  // MARK: - Session and engine

  private func routeChanged() {
    // Glasses connected or disconnected: re-pick the input and rebuild the tap for its rate.
    rebuild(micAllowed: AVAudioApplication.shared.recordPermission == .granted)
  }

  private func rebuild(micAllowed: Bool) {
    let session = AVAudioSession.sharedInstance()
    do {
      try session.setCategory(.playAndRecord, mode: .default, options: [.allowBluetoothHFP, .defaultToSpeaker])
      try session.setActive(true)
      if let glasses = session.availableInputs?.first(where: { $0.portType == .bluetoothHFP }),
        session.preferredInput?.uid != glasses.uid
      {
        try session.setPreferredInput(glasses)
      }
    } catch {
      NSLog("[Relay] audio session: \(error)")
    }

    let input = engine.inputNode
    input.removeTap(onBus: 0)
    let format = input.inputFormat(forBus: 0)
    // A zero format (no mic, or permission denied) would crash installTap.
    if micAllowed, format.sampleRate > 0, format.channelCount > 0 {
      let rate = format.sampleRate <= 8000 ? 8000 : 16000
      capture.configure(from: format, toRate: rate)
      input.installTap(onBus: 0, bufferSize: 1024, format: format) { [capture] buffer, _ in
        capture.ingest(buffer)
      }
      let onGlasses = session.currentRoute.inputs.contains { $0.portType == .bluetoothHFP }
      inputLabel = "\(onGlasses ? "glasses" : "phone") mic \(rate / 1000) kHz"
    } else {
      inputLabel = micAllowed ? "no mic" : "mic not allowed"
    }
    ensureRunning()
  }

  private func ensureRunning() {
    guard !engine.isRunning else { return }
    engine.prepare()
    do { try engine.start() } catch { NSLog("[Relay] engine start: \(error)") }
  }

  static func makeBuffer(pcm16 data: Data, rate: Double, to target: AVAudioFormat) -> AVAudioPCMBuffer? {
    let count = data.count / 2
    guard count > 0, rate > 0,
      let source = AVAudioFormat(standardFormatWithSampleRate: rate, channels: 1),
      let buffer = AVAudioPCMBuffer(pcmFormat: source, frameCapacity: AVAudioFrameCount(count))
    else { return nil }
    buffer.frameLength = AVAudioFrameCount(count)
    let out = buffer.floatChannelData![0]
    data.withUnsafeBytes { raw in
      let samples = raw.bindMemory(to: Int16.self)
      for i in 0..<count { out[i] = Float(Int16(littleEndian: samples[i])) / 32768 }
    }
    if rate == target.sampleRate { return buffer }
    guard let converter = AVAudioConverter(from: source, to: target),
      let converted = AVAudioPCMBuffer(
        pcmFormat: target, frameCapacity: AVAudioFrameCount(Double(count) * target.sampleRate / rate) + 64)
    else { return nil }
    var fed = false
    var error: NSError?
    converter.convert(to: converted, error: &error) { _, status in
      if fed {
        status.pointee = .endOfStream
        return nil
      }
      fed = true
      status.pointee = .haveData
      return buffer
    }
    return error == nil ? converted : nil
  }
}

extension AudioIO: AVSpeechSynthesizerDelegate {
  nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
    let id = ObjectIdentifier(utterance)
    Task { @MainActor in self.utteranceFinished(id) }
  }
}

/// Converts mic buffers to 16-bit mono at 8 or 16 kHz and cuts them into 100 ms chunks.
/// Runs on the audio tap thread; everything is behind a lock.
private final class Capture: @unchecked Sendable {
  var onChunk: (@Sendable (Data, Int) -> Void)?

  private let lock = NSLock()
  private var converter: AVAudioConverter?
  private var outFormat: AVAudioFormat?
  private var rate = 16000
  private var active = false
  private var pending = Data()

  func configure(from input: AVAudioFormat, toRate rate: Int) {
    lock.lock()
    defer { lock.unlock() }
    self.rate = rate
    outFormat = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: Double(rate), channels: 1, interleaved: true)
    converter = outFormat.flatMap { AVAudioConverter(from: input, to: $0) }
  }

  func begin() {
    lock.lock()
    pending = Data()
    converter?.reset()
    active = true
    lock.unlock()
  }

  func end() {
    lock.lock()
    active = false
    let rest = pending
    pending = Data()
    let rate = self.rate
    lock.unlock()
    if !rest.isEmpty { onChunk?(rest, rate) }
  }

  func ingest(_ buffer: AVAudioPCMBuffer) {
    lock.lock()
    guard active, let converter, let outFormat else {
      lock.unlock()
      return
    }
    let capacity = AVAudioFrameCount(Double(buffer.frameLength) * outFormat.sampleRate / buffer.format.sampleRate) + 64
    guard let out = AVAudioPCMBuffer(pcmFormat: outFormat, frameCapacity: capacity) else {
      lock.unlock()
      return
    }
    var fed = false
    var error: NSError?
    // .noDataNow keeps the resampler's state between tap buffers.
    converter.convert(to: out, error: &error) { _, status in
      if fed {
        status.pointee = .noDataNow
        return nil
      }
      fed = true
      status.pointee = .haveData
      return buffer
    }
    if error == nil, let samples = out.int16ChannelData?[0] {
      pending.append(Data(bytes: samples, count: Int(out.frameLength) * 2))
    }
    let chunkBytes = rate / 10 * 2
    var chunks: [Data] = []
    while pending.count >= chunkBytes {
      chunks.append(pending.prefix(chunkBytes))
      pending.removeFirst(chunkBytes)
    }
    let rate = self.rate
    lock.unlock()
    for chunk in chunks { onChunk?(Data(chunk), rate) }
  }
}
