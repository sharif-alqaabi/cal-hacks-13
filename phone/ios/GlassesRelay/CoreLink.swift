import Foundation

/// The /stream WebSocket to core. Reconnects on its own (0.5 s, 1 s, then every 2 s) so a drop
/// recovers within the PRD's 5 s. Frames are dropped rather than queued when the socket is
/// behind or down; nothing is buffered across a reconnect.
@MainActor
final class CoreLink {
  enum State: Equatable { case idle, connecting, connected, reconnecting }

  var onState: ((State) -> Void)?
  var onMessage: ((InboundMsg) -> Void)?
  private(set) var state: State = .idle

  private let session = URLSession(configuration: .default)
  private let encoder = JSONEncoder()
  private var url: URL?
  private var task: URLSessionWebSocketTask?
  private var generation = 0
  private var attempt = 0
  private var framesInFlight = 0
  private var lastPong = Date()
  /// Round trip of the last heartbeat ping. Pings queue behind frames on the same socket, so a
  /// long round trip means frames are piling up in the send buffer.
  private var rtt: TimeInterval = 0
  private static let congestedRTT: TimeInterval = 0.35
  private var heartbeat: Task<Void, Never>?
  private var retry: Task<Void, Never>?

  private static let backoff: [Double] = [0.5, 1, 2]
  private static let maxFramesInFlight = 2

  func connect(to url: URL) {
    relayLog("connecting to \(url.absoluteString)")
    self.url = url
    attempt = 0
    open()
  }

  func disconnect() {
    url = nil
    teardown()
    set(.idle)
  }

  /// Sends one message. Frames (`isFrame`) are skipped while two are still in flight so a slow
  /// link drops frames instead of building delay.
  func send<T: Encodable>(_ msg: T, isFrame: Bool = false) {
    guard state == .connected, let task else { return }
    if isFrame && framesInFlight >= Self.maxFramesInFlight { return }
    guard let data = try? encoder.encode(msg), let text = String(data: data, encoding: .utf8) else { return }
    if isFrame { framesInFlight += 1 }
    let gen = generation
    task.send(.string(text)) { [weak self] error in
      Task { @MainActor in
        guard let self, gen == self.generation else { return }
        if isFrame { self.framesInFlight -= 1 }
        if let error { self.fail(gen, "send: \(error.localizedDescription)") }
      }
    }
  }

  /// Sends a message already encoded as JSON text (frames, encoded off the main thread).
  func sendText(_ text: String, isFrame: Bool) {
    guard state == .connected, let task else { return }
    if isFrame && (framesInFlight >= Self.maxFramesInFlight || rtt > Self.congestedRTT) { return }
    if isFrame { framesInFlight += 1 }
    let gen = generation
    task.send(.string(text)) { [weak self] error in
      Task { @MainActor in
        guard let self, gen == self.generation else { return }
        if isFrame { self.framesInFlight -= 1 }
        if let error { self.fail(gen, "send: \(error.localizedDescription)") }
      }
    }
  }

  var isConnected: Bool { state == .connected }

  // MARK: - Private

  private func open() {
    guard let url else { return }
    teardown()
    rtt = 0
    let gen = generation
    let t = session.webSocketTask(with: url)
    t.maximumMessageSize = 16 << 20
    task = t
    set(attempt == 0 ? .connecting : .reconnecting)
    t.resume()
    receive(t, gen)
    // URLSessionWebSocketTask has no open callback without a delegate; the first pong proves
    // the handshake finished.
    t.sendPing { [weak self] error in
      Task { @MainActor in
        guard let self, gen == self.generation else { return }
        if let error { self.fail(gen, "connect: \(error.localizedDescription)"); return }
        self.attempt = 0
        self.set(.connected)
        self.startHeartbeat(t, gen)
      }
    }
  }

  private func teardown() {
    generation += 1
    heartbeat?.cancel()
    retry?.cancel()
    task?.cancel(with: .goingAway, reason: nil)
    task = nil
    framesInFlight = 0
  }

  private func receive(_ t: URLSessionWebSocketTask, _ gen: Int) {
    t.receive { [weak self] result in
      Task { @MainActor in
        guard let self, gen == self.generation else { return }
        switch result {
        case .failure(let error):
          self.fail(gen, "receive: \(error.localizedDescription)")
        case .success(let message):
          let data: Data?
          switch message {
          case .string(let s): data = Data(s.utf8)
          case .data(let d): data = d
          @unknown default: data = nil
          }
          if let data, let msg = try? JSONDecoder().decode(InboundMsg.self, from: data) {
            self.onMessage?(msg)
          }
          self.receive(t, gen)
        }
      }
    }
  }

  /// A ping every second; no pong for 3 s counts as a drop, so a dead wifi link is noticed
  /// even when nothing is being sent.
  private func startHeartbeat(_ t: URLSessionWebSocketTask, _ gen: Int) {
    lastPong = Date()
    heartbeat = Task { [weak self] in
      while !Task.isCancelled {
        try? await Task.sleep(for: .seconds(1))
        guard let self, gen == self.generation, !Task.isCancelled else { return }
        if Date().timeIntervalSince(self.lastPong) > 3 { self.fail(gen, "no pong for 3 s"); return }
        let sent = Date()
        t.sendPing { [weak self] error in
          Task { @MainActor in
            guard let self, gen == self.generation else { return }
            if let error {
              self.fail(gen, "ping: \(error.localizedDescription)")
            } else {
              self.lastPong = Date()
              let wasCongested = self.rtt > Self.congestedRTT
              self.rtt = self.lastPong.timeIntervalSince(sent)
              if (self.rtt > Self.congestedRTT) != wasCongested {
                relayLog(wasCongested ? "link clear (\(Int(self.rtt * 1000)) ms), sending frames" : "link backed up (\(Int(self.rtt * 1000)) ms), dropping frames")
              }
            }
          }
        }
      }
    }
  }

  private func fail(_ gen: Int, _ reason: String) {
    guard gen == generation, url != nil else { return }
    relayLog("link dropped (\(reason)); retry \(attempt + 1)")
    teardown()
    set(.reconnecting)
    let delay = Self.backoff[min(attempt, Self.backoff.count - 1)]
    attempt += 1
    retry = Task { [weak self] in
      try? await Task.sleep(for: .seconds(delay))
      guard !Task.isCancelled else { return }
      self?.open()
    }
  }

  private func set(_ new: State) {
    guard new != state else { return }
    state = new
    onState?(new)
  }
}
