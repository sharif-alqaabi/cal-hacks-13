import Foundation

/// Logs to the Xcode console and to Documents/relay.log on the phone, so a run can be read back
/// over the cable without Xcode attached:
///   xcrun devicectl device copy from --device <udid> --domain-type appDataContainer \
///     --domain-identifier <bundle id> --source Documents/relay.log --destination relay.log
func relayLog(_ message: String) {
  NSLog("[Relay] %@", message)
  RelayLogFile.shared.append(message)
}

final class RelayLogFile: @unchecked Sendable {
  static let shared = RelayLogFile()
  private let queue = DispatchQueue(label: "relay.log")
  private let url: URL? = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first?
    .appendingPathComponent("relay.log")
  private let stamp: DateFormatter = {
    let f = DateFormatter()
    f.dateFormat = "HH:mm:ss.SSS"
    return f
  }()

  func append(_ message: String) {
    let line = "\(stamp.string(from: Date())) \(message)\n"
    queue.async { [url] in
      guard let url, let data = line.data(using: .utf8) else { return }
      // Start over past 1 MB so the file can't grow without bound.
      if let size = try? FileManager.default.attributesOfItem(atPath: url.path)[.size] as? Int, size > 1 << 20 {
        try? FileManager.default.removeItem(at: url)
      }
      if let h = try? FileHandle(forWritingTo: url) {
        h.seekToEndOfFile()
        h.write(data)
        try? h.close()
      } else {
        try? data.write(to: url)
      }
    }
  }
}
