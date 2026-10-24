import Foundation

// /stream WebSocket messages. Source of truth: core/contracts/stream.py.
// `ts` is Unix seconds as a float.

// MARK: phone -> core

struct FrameMsg: Encodable {
  let type = "frame"
  let ts: Double
  let jpeg_b64: String
  let w: Int
  let h: Int
  let snap_id: String?  // set only when answering a snap
}

struct AudioMsg: Encodable {
  let type = "audio"
  let ts: Double
  let pcm16_b64: String  // mono, little-endian 16-bit PCM
  let rate: Int          // 8000 (glasses HFP) or 16000 (phone mic)
}

struct PttMsg: Encodable {
  let type = "ptt"
  let state: String  // "down" | "up"
}

// MARK: core -> phone

/// Covers both `say` and `snap`; fields that don't apply are nil.
struct InboundMsg: Decodable {
  let type: String
  let id: String?
  let text: String?
  let pcm16_b64: String?
  let rate: Int?
  let urgent: Bool?
  let snap_id: String?
}

enum Clock {
  static var now: Double { Date().timeIntervalSince1970 }
}
