import UIKit

enum SourceKind: String, CaseIterable, Identifiable {
  case glasses
  #if DEBUG
  case mockGlasses
  #endif
  case phoneCamera

  var id: String { rawValue }

  var label: String {
    switch self {
    case .glasses: return "Glasses camera"
    #if DEBUG
    case .mockGlasses: return "Mock glasses (debug)"
    #endif
    case .phoneCamera: return "Phone camera (fallback)"
    }
  }
}

enum SourceState: Equatable {
  case stopped
  case starting
  /// Waiting for the wearer: glasses off, folded, not registered, or permission missing.
  case waiting(String)
  case streaming
  /// Device-initiated pause (a tap on the glasses, taking them off). Nothing is sent.
  case paused
  case failed(String)
}

/// Anything that produces camera images: the glasses (real or mock) or the phone camera.
/// Every source feeds the same encoder and socket, so switching needs no backend change.
@MainActor
protocol FrameSource: AnyObject {
  /// Called on a background thread for every decoded frame.
  var onImage: (@Sendable (UIImage) -> Void)? { get set }
  var onState: ((SourceState) -> Void)? { get set }
  func start()
  func stop()
}
