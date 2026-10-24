@preconcurrency import AVFoundation
import CoreImage
import UIKit

/// Fallback camera (PRD G-11): the phone's back camera, e.g. worn on a lanyard.
@MainActor
final class PhoneCameraSource: NSObject, FrameSource {
  var onImage: (@Sendable (UIImage) -> Void)? {
    didSet { delegate.onImage = onImage }
  }
  var onState: ((SourceState) -> Void)?

  private let session = AVCaptureSession()
  private let queue = DispatchQueue(label: "relay.phone-camera")
  private let delegate = SampleDelegate()
  private var configured = false

  func start() {
    onState?(.starting)
    Task {
      guard await AVCaptureDevice.requestAccess(for: .video) else {
        onState?(.failed("Camera permission denied. Allow it in Settings."))
        return
      }
      if !configured {
        guard configure() else {
          onState?(.failed("No phone camera available."))
          return
        }
        configured = true
      }
      let session = self.session
      queue.async { session.startRunning() }
      onState?(.streaming)
    }
  }

  func stop() {
    let session = self.session
    queue.async { session.stopRunning() }
    onState?(.stopped)
  }

  private func configure() -> Bool {
    guard let camera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back),
      let input = try? AVCaptureDeviceInput(device: camera)
    else { return false }
    session.beginConfiguration()
    session.sessionPreset = .vga640x480
    if session.canAddInput(input) { session.addInput(input) }
    let output = AVCaptureVideoDataOutput()
    output.alwaysDiscardsLateVideoFrames = true
    output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
    output.setSampleBufferDelegate(delegate, queue: queue)
    if session.canAddOutput(output) { session.addOutput(output) }
    session.commitConfiguration()
    return true
  }

  private final class SampleDelegate: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate, @unchecked Sendable {
    var onImage: (@Sendable (UIImage) -> Void)?
    private let context = CIContext()

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
      guard let pixels = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
      let image = CIImage(cvPixelBuffer: pixels)
      guard let cg = context.createCGImage(image, from: image.extent) else { return }
      // The back camera delivers landscape buffers; .right makes them upright for a phone held
      // in portrait.
      onImage?(UIImage(cgImage: cg, scale: 1, orientation: .right))
    }
  }
}
