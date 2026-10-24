import MWDATCore
import SwiftUI

/// One large push-to-talk area (PRD G-6) plus a settings sheet. Works eyes-closed: VoiceOver
/// passes touches straight through to the talk area, and every state change is also spoken.
struct ContentView: View {
  let model: RelayModel
  @State private var showSettings = false

  var body: some View {
    VStack(spacing: 0) {
      statusBar
      talkArea
    }
    .background(Color.black)
    .onAppear { model.start() }
    .sheet(isPresented: $showSettings) { SettingsView(model: model) }
    .alert(
      "Something went wrong",
      isPresented: Binding(get: { model.errorMessage != nil }, set: { if !$0 { model.errorMessage = nil } })
    ) {
      Button("OK") { model.errorMessage = nil }
    } message: {
      Text(model.errorMessage ?? "")
    }
  }

  private var statusBar: some View {
    HStack(alignment: .top) {
      VStack(alignment: .leading, spacing: 4) {
        Text(linkText).font(.headline).foregroundStyle(linkColor)
        Text(sourceText).font(.subheadline).foregroundStyle(.white.opacity(0.8))
        Text("\(model.framesPerSecond) fps \(model.lastFrameSize) · \(model.audioInputLabel)")
          .font(.caption.monospaced()).foregroundStyle(.white.opacity(0.6))
        if !model.lastReply.isEmpty {
          Text(model.lastReply).font(.caption).foregroundStyle(.white.opacity(0.8)).lineLimit(2)
        }
      }
      .accessibilityElement(children: .combine)
      Spacer()
      Button {
        showSettings = true
      } label: {
        Image(systemName: "gearshape.fill").font(.title).foregroundStyle(.white).padding(8)
      }
      .accessibilityLabel("Settings")
    }
    .padding()
  }

  private var talkArea: some View {
    ZStack {
      RoundedRectangle(cornerRadius: 32)
        .fill(model.talking ? Color.red : Color(white: 0.15))
      VStack(spacing: 12) {
        Image(systemName: model.talking ? "waveform" : "mic.fill").font(.system(size: 72))
        Text(model.talking ? "Listening…" : "Hold to talk").font(.largeTitle.bold())
      }
      .foregroundStyle(.white)
    }
    .padding()
    .contentShape(Rectangle())
    .gesture(
      DragGesture(minimumDistance: 0)
        .onChanged { _ in model.pttDown() }
        .onEnded { _ in model.pttUp() }
    )
    .accessibilityElement()
    .accessibilityLabel(model.talking ? "Listening" : "Hold to talk")
    .accessibilityHint("Touch and hold anywhere here while you speak, then let go.")
    .accessibilityAddTraits(.allowsDirectInteraction)
  }

  private var linkText: String {
    switch model.linkState {
    case .idle: return "Not connected"
    case .connecting: return "Connecting to core…"
    case .connected: return "Connected"
    case .reconnecting: return "Reconnecting…"
    }
  }

  private var linkColor: Color {
    switch model.linkState {
    case .connected: return .green
    case .idle: return .gray
    case .connecting, .reconnecting: return .orange
    }
  }

  private var sourceText: String {
    let name = model.sourceKind.label
    switch model.sourceState {
    case .stopped: return "\(name): off"
    case .starting: return "\(name): starting"
    case .waiting(let why): return "\(name): \(why)"
    case .streaming: return "\(name): streaming"
    case .paused: return "\(name): paused"
    case .failed(let why): return "\(name): \(why)"
    }
  }
}

struct SettingsView: View {
  @Bindable var model: RelayModel
  @Environment(\.dismiss) private var dismiss

  var body: some View {
    NavigationStack {
      Form {
        Section {
          TextField("ws://laptop-ip:8000/stream", text: $model.coreURL)
            .keyboardType(.URL)
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
          Button("Reconnect") { model.connect() }
        } header: {
          Text("Core address")
        } footer: {
          Text("The laptop's address on venue wifi, or a tunnel URL (wss://…).")
        }

        Section("Camera") {
          Picker("Source", selection: $model.sourceKind) {
            ForEach(SourceKind.allCases) { Text($0.label).tag($0) }
          }
        }

        Section("Glasses") {
          LabeledContent("Meta AI", value: registrationText)
          if model.registration == .registered {
            Button("Disconnect glasses", role: .destructive) { model.disconnectGlasses() }
          } else {
            Button("Connect glasses") { model.connectGlasses() }
              .disabled(model.registration == .registering)
          }
        }

        if let ms = model.urgentLatencyMs {
          Section("Diagnostics") {
            LabeledContent("Last urgent reply", value: "\(ms) ms to start")
          }
        }
      }
      .navigationTitle("Settings")
      .toolbar {
        ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
      }
    }
  }

  private var registrationText: String {
    switch model.registration {
    case .registered: return "Connected"
    case .registering: return "Connecting…"
    case .available: return "Not connected"
    case .unavailable: return "Unavailable"
    @unknown default: return "Unknown"
    }
  }
}
