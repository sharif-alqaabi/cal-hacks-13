import QuartzCore
import UIKit

/// Turns camera images into `frame` messages: at most `fps` per second, long side <= 640 px,
/// JPEG quality 0.7. Keeps only the latest full-resolution image (in memory, never on disk)
/// so a `snap` can be answered with a sharper frame. Safe to call from any thread.
final class FrameEncoder: @unchecked Sendable {
  var fps: Double = 5
  /// Called on the encoder's queue.
  var onFrame: (@Sendable (FrameMsg) -> Void)?

  private let queue = DispatchQueue(label: "relay.frame-encoder", qos: .userInitiated)
  private let lock = NSLock()
  private var latest: UIImage?
  private var lastSent: CFTimeInterval = 0
  private var busy = false

  static let streamLongSide: CGFloat = 640
  static let snapLongSide: CGFloat = 1280

  func submit(_ image: UIImage) {
    lock.lock()
    latest = image
    let now = CACurrentMediaTime()
    let due = !busy && now - lastSent >= 1 / fps
    if due {
      busy = true
      lastSent = now
    }
    lock.unlock()
    guard due else { return }
    queue.async { [weak self] in
      let frame = Self.encode(image, longSide: Self.streamLongSide, snapID: nil)
      guard let self else { return }
      self.lock.lock()
      self.busy = false
      self.lock.unlock()
      if let frame { self.onFrame?(frame) }
    }
  }

  /// Answers core's `snap` with the latest image at up to 1280 px.
  func snap(_ id: String) {
    lock.lock()
    let image = latest
    lock.unlock()
    guard let image else { return }
    queue.async { [weak self] in
      if let frame = Self.encode(image, longSide: Self.snapLongSide, snapID: id) { self?.onFrame?(frame) }
    }
  }

  /// Forgets the held image, e.g. when the glasses pause.
  func clear() {
    lock.lock()
    latest = nil
    lock.unlock()
  }

  static func encode(_ image: UIImage, longSide: CGFloat, snapID: String?) -> FrameMsg? {
    let px = CGSize(width: image.size.width * image.scale, height: image.size.height * image.scale)
    guard px.width > 0, px.height > 0 else { return nil }
    let k = min(1, longSide / max(px.width, px.height))
    let size = CGSize(width: (px.width * k).rounded(), height: (px.height * k).rounded())
    let format = UIGraphicsImageRendererFormat()
    format.scale = 1
    format.opaque = true
    // Drawing also applies the image orientation, so the JPEG is always upright.
    let jpeg = UIGraphicsImageRenderer(size: size, format: format).jpegData(withCompressionQuality: 0.7) { _ in
      image.draw(in: CGRect(origin: .zero, size: size))
    }
    return FrameMsg(ts: Clock.now, jpeg_b64: jpeg.base64EncodedString(), w: Int(size.width), h: Int(size.height), snap_id: snapID)
  }
}
