import MWDATCore
import SwiftUI

@main
struct GlassesRelayApp: App {
  @State private var model: RelayModel

  init() {
    // Must run before anything touches Wearables.shared.
    do {
      try Wearables.configure()
    } catch {
      relayLog("Wearables.configure failed: \(error)")
    }
    _model = State(wrappedValue: RelayModel())
  }

  var body: some Scene {
    WindowGroup {
      ContentView(model: model)
        .preferredColorScheme(.dark)
        // Callback from the Meta AI app after registration or a permission request.
        .onOpenURL { url in
          relayLog("opened by URL \(url.absoluteString)")
          Task {
            do { _ = try await Wearables.shared.handleUrl(url) } catch { relayLog("handleUrl failed: \(error)") }
          }
        }
    }
  }
}
