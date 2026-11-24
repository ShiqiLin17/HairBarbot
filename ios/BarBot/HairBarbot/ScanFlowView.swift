//
//  ScanFlowView.swift
//  HairBarbot
//
//  The full-screen guided scan: a step indicator, an X to stop, and one screen
//  per step of ScanFlow.
//

import SwiftUI
import UIKit
import StandardCyborgFusion
import StandardCyborgUI

struct ScanFlowView: View {
    @State private var flow: ScanFlow
    @State private var sounds = ScanSounds()
    @State private var confirmingCancel = false
    /// Remembered between scans and launches.
    @AppStorage("scanSoundsOn") private var soundsOn = true
    /// Called when the flow closes; with the saved person's name if they tapped Start Haircut.
    let onClose: (_ startHaircutFor: String?) -> Void

    init(suggestedName: String = "", onClose: @escaping (_ startHaircutFor: String?) -> Void) {
        _flow = State(initialValue: ScanFlow(suggestedName: suggestedName))
        self.onClose = onClose
    }

    var body: some View {
        VStack(spacing: 0) {
            if !isSaved {
                topBar
            }
            content
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .brandBackground()
        .onAppear {
            flow.begin()
            sounds.isMuted = !soundsOn
            sounds.start()
        }
        .onChange(of: soundsOn) { _, on in sounds.isMuted = !on }
        .onDisappear { sounds.stop() }
        .confirmationDialog("Stop scanning?", isPresented: $confirmingCancel, titleVisibility: .visible) {
            Button("Stop and Discard Scans") {
                flow.discard()
                onClose(nil)
            }
            Button("Keep Scanning", role: .cancel) {}
        } message: {
            Text("The scans you've made so far will be lost.")
        }
    }

    private var isSaved: Bool {
        if case .saved = flow.step { return true }
        return false
    }

    // MARK: - Top bar: X, step indicator, sound toggle

    private var topBar: some View {
        HStack(spacing: 12) {
            Button {
                if flow.step == .prep || flow.step == .howTo {
                    flow.discard()
                    onClose(nil)
                } else {
                    confirmingCancel = true
                }
            } label: {
                Image(systemName: "xmark")
                    .font(.headline)
                    .foregroundStyle(Color.brand.ink)
                    .frame(width: 44, height: 44)
            }
            .accessibilityLabel("Close")

            StepIndicator(current: stepIndex)
                .frame(maxWidth: .infinity)

            Button {
                soundsOn.toggle()
            } label: {
                Image(systemName: soundsOn ? "speaker.wave.2.fill" : "speaker.slash.fill")
                    .font(.headline)
                    .foregroundStyle(Color.brand.primary)
                    .frame(width: 44, height: 44)
            }
            .accessibilityLabel(soundsOn ? "Turn sounds off" : "Turn sounds on")
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(Color.brand.surface)
        .overlay(alignment: .bottom) {
            Rectangle().fill(Color.brand.line).frame(height: BrandMetrics.borderWidth)
        }
    }

    /// 0–2 = right, left, top; 3 = save. Nil before scanning starts.
    private var stepIndex: Int? {
        switch flow.step {
        case .prep, .howTo: nil
        case .scan(let pass), .review(let pass): pass.rawValue
        case .save, .saved: 3
        }
    }

    // MARK: - Steps

    @ViewBuilder
    private var content: some View {
        switch flow.step {
        case .prep:
            PrepScreen { flow.step = .howTo }
        case .howTo:
            HowToScreen(sounds: sounds, soundsOn: $soundsOn) { flow.step = .scan(.right) }
        case .scan(let pass):
            GuidedScanView(pass: pass, flow: flow, sounds: sounds)
                .id(pass)   // a fresh scanner for every pass and every redo
        case .review(let pass):
            ScanReviewScreen(pass: pass, flow: flow)
        case .save:
            SaveHeadScreen(flow: flow)
        case .saved(let name):
            SavedScreen(name: name,
                        onStartHaircut: { onClose(name) },
                        onDone: { onClose(nil) })
        }
    }
}

/// Right · Left · Top · Save, with the current step highlighted.
private struct StepIndicator: View {
    let current: Int?
    private let titles = ["Right", "Left", "Top", "Save"]

    var body: some View {
        HStack(spacing: 6) {
            ForEach(titles.indices, id: \.self) { index in
                let done = current.map { index < $0 } ?? false
                let active = index == current
                HStack(spacing: 4) {
                    if done {
                        Image(systemName: "checkmark")
                            .font(.caption2.bold())
                    }
                    Text(titles[index])
                        .font(.caption.weight(active ? .bold : .medium))
                }
                .foregroundStyle(active ? Color.brand.onPrimary : (done ? Color.brand.primary : Color.brand.muted))
                .padding(.horizontal, 9)
                .padding(.vertical, 5)
                .background(active ? Color.brand.primary : Color.brand.surface2, in: Capsule())
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(current.map { "Step \($0 + 1) of 4: \(titles[$0])" } ?? "Getting ready")
    }
}

// MARK: - 2a. Get ready

private struct PrepScreen: View {
    let onNext: () -> Void

    var body: some View {
        StepLayout(title: "Get ready to scan",
                   subtitle: "Three short scans build a 3D model of the head. It takes about two minutes.",
                   buttonTitle: "Next", action: onNext) {
            VStack(alignment: .leading, spacing: 18) {
                IconRow(systemImage: "person.crop.circle.badge.checkmark",
                        title: "Wear a swim cap",
                        detail: "Hair makes the model too big. A cap shows the real head shape.")
                IconRow(systemImage: "eyeglasses",
                        title: "Take off glasses and earbuds",
                        detail: "They show up as bumps on the head.")
                IconRow(systemImage: "sun.max",
                        title: "Find bright, even light",
                        detail: "Avoid a bright window behind the head.")
                IconRow(systemImage: "iphone",
                        title: "Put the phone on a stand",
                        detail: "At head height, about an arm's length away, screen facing you.")
            }
            .brandCard(padding: 20)
        }
    }
}

// MARK: - 2b. How scanning works

private struct HowToScreen: View {
    let sounds: ScanSounds
    @Binding var soundsOn: Bool
    let onReady: () -> Void

    var body: some View {
        StepLayout(title: "How scanning works",
                   subtitle: "Move slowly. A full turn should take about 15–20 seconds. Moving fast makes the scanner lose its place.",
                   buttonTitle: "I'm Ready", action: onReady) {
            VStack(alignment: .leading, spacing: 16) {
                Text("What the sounds mean")
                    .font(.headline)
                    .foregroundStyle(Color.brand.ink)
                soundRow(.tick, systemImage: "checkmark.circle", title: "Soft tick",
                         detail: "Tracking is good. Keep going.")
                soundRow(.warning, systemImage: "tortoise", title: "Low beep",
                         detail: "Slow down.")
                soundRow(.done, systemImage: "bell", title: "Chime",
                         detail: "The scan is finished. It stops by itself when it can't see more of the head.")
            }
            .brandCard(padding: 20)

            VStack(alignment: .leading, spacing: 12) {
                IconRow(systemImage: "speaker.wave.2",
                        title: "Spoken prompts",
                        detail: "You won't see the screen while you turn, so the phone tells you what to do.")
                Toggle("Sounds and voice", isOn: $soundsOn)
                    .font(.body.weight(.semibold))
                    .foregroundStyle(Color.brand.ink)
                    .tint(Color.brand.primary)
            }
            .brandCard(padding: 20)
        }
    }

    private func soundRow(_ cue: ScanSounds.Cue, systemImage: String, title: String, detail: String) -> some View {
        IconRow(systemImage: systemImage, title: title, detail: detail) {
            Button {
                sounds.play(cue)
            } label: {
                Image(systemName: "play.circle.fill")
                    .font(.title)
                    .foregroundStyle(Color.brand.primary)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Play \(title.lowercased())")
        }
    }
}

// MARK: - 2d / 2f / 2h. Review

private struct ScanReviewScreen: View {
    let pass: ScanPass
    let flow: ScanFlow

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 6) {
                Text(title)
                    .font(.title2.bold())
                    .foregroundStyle(Color.brand.ink)
                Text(question)
                    .font(.body)
                    .foregroundStyle(Color.brand.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }

            ZStack {
                RoundedRectangle(cornerRadius: BrandMetrics.cardRadius)
                    .fill(Color.brand.surface2)
                if let cloud = flow.reviewCloud {
                    PointCloudView(pointCloud: cloud)
                        .clipShape(RoundedRectangle(cornerRadius: BrandMetrics.cardRadius))
                        .overlay(alignment: .bottomTrailing) {
                            Label("Drag to turn", systemImage: "hand.draw")
                                .font(.caption)
                                .foregroundStyle(Color.brand.muted)
                                .padding(10)
                        }
                } else if flow.isMerging {
                    VStack(spacing: 12) {
                        ProgressView()
                        Text("Putting the scans together…")
                            .font(.headline)
                            .foregroundStyle(Color.brand.ink)
                    }
                } else if let error = flow.reviewError {
                    Label(error, systemImage: "exclamationmark.circle")
                        .font(.body)
                        .foregroundStyle(Color.brand.ink)
                        .padding()
                } else {
                    ProgressView()
                }
            }
            .overlay(RoundedRectangle(cornerRadius: BrandMetrics.cardRadius)
                .strokeBorder(Color.brand.line, lineWidth: BrandMetrics.borderWidth))
            .frame(maxHeight: .infinity)

            if let warning = flow.reviewWarning {
                Label(warning, systemImage: "exclamationmark.triangle.fill")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Color.brand.warn)
            }

            HStack(spacing: 12) {
                Button(redoTitle) { flow.redo(pass) }
                    .buttonStyle(.brandSecondary)
                Button(approveTitle) { flow.approve(pass) }
                    .buttonStyle(.brandPrimary)
                    .disabled(flow.reviewCloud == nil || flow.isMerging || flow.reviewError != nil)
            }
        }
        .padding(16)
    }

    private var title: String {
        switch pass {
        case .right: "Check scan 1"
        case .left: "Check scans 1 and 2 together"
        case .top: "Check all three scans together"
        }
    }

    private var question: String {
        switch pass {
        case .right: "Does this look like the front and right side of the head? Small holes are fine."
        case .left: "Does this look like one head? Check for a doubled face, nose or ears."
        case .top: "Does this look like one head, now with the top filled in? Check for a doubled face, nose or ears."
        }
    }

    private var redoTitle: String {
        switch pass {
        case .right: "Redo"
        case .left: "Redo Left Scan"
        case .top: "Redo Top Scan"
        }
    }

    private var approveTitle: String { pass == .right ? "Looks Good" : "Looks Right" }
}

/// StandardCyborg's 3D point view without its buttons. Drag to turn, pinch to zoom.
private struct PointCloudView: UIViewControllerRepresentable {
    let pointCloud: SCPointCloud

    func makeUIViewController(context: Context) -> ScenePreviewViewController {
        let preview = ScenePreviewViewController(pointCloud: pointCloud, meshTexturing: nil, landmarks: nil)
        // No titles → StandardCyborg hides both buttons.
        preview.leftButton.setTitle(nil, for: .normal)
        preview.rightButton.setTitle(nil, for: .normal)
        let background = UIColor(Color.brand.surface2)
        preview.view.backgroundColor = background
        preview.sceneView.backgroundColor = background
        return preview
    }

    func updateUIViewController(_ preview: ScenePreviewViewController, context: Context) {}
}

// MARK: - 2i. Save

private struct SaveHeadScreen: View {
    let flow: ScanFlow
    @Environment(HeadStore.self) private var heads
    @State private var name = ""
    @State private var confirmingReplace = false
    @State private var saveError: String?
    @FocusState private var nameFocused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Save this head")
                .font(.title2.bold())
                .foregroundStyle(Color.brand.ink)

            ZStack {
                RoundedRectangle(cornerRadius: BrandMetrics.cardRadius)
                    .fill(Color.brand.surface2)
                if let mesh = flow.fittedMesh {
                    HeadMeshSceneView(mesh: mesh,
                                      color: UIColor(Color.brand.warmWhite),
                                      background: UIColor(Color.brand.surface2))
                        .clipShape(RoundedRectangle(cornerRadius: BrandMetrics.cardRadius))
                } else if flow.isFitting {
                    VStack(spacing: 12) {
                        ProgressView()
                        Text("Building the head model…")
                            .font(.headline)
                            .foregroundStyle(Color.brand.ink)
                    }
                } else if let error = flow.fitError {
                    VStack(spacing: 16) {
                        Label(error, systemImage: "exclamationmark.circle")
                            .font(.body)
                            .foregroundStyle(Color.brand.ink)
                        Button("Scan Again") { flow.startOver() }
                            .buttonStyle(.brandPrimary)
                    }
                    .padding()
                }
            }
            .overlay(RoundedRectangle(cornerRadius: BrandMetrics.cardRadius)
                .strokeBorder(Color.brand.line, lineWidth: BrandMetrics.borderWidth))
            .frame(maxHeight: .infinity)

            if flow.fitError == nil {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Whose head is this?")
                        .font(.headline)
                        .foregroundStyle(Color.brand.ink)
                    TextField("Name", text: $name)
                        .textContentType(.name)
                        .submitLabel(.done)
                        .focused($nameFocused)
                        .padding(14)
                        .background(Color.brand.surface, in: RoundedRectangle(cornerRadius: BrandMetrics.cardRadius))
                        .overlay(RoundedRectangle(cornerRadius: BrandMetrics.cardRadius)
                            .strokeBorder(Color.brand.line, lineWidth: BrandMetrics.borderWidth))
                    if let saveError {
                        Label(saveError, systemImage: "exclamationmark.circle")
                            .font(.subheadline)
                            .foregroundStyle(Color.brand.ink)
                    }
                }
                Button("Save", action: trySave)
                    .buttonStyle(.brandPrimary)
                    .disabled(!flow.canSave || trimmedName.isEmpty)
            }
        }
        .padding(16)
        .onAppear { if name.isEmpty { name = flow.suggestedName } }
        .confirmationDialog("Replace \(trimmedName)'s saved head?", isPresented: $confirmingReplace,
                            titleVisibility: .visible) {
            Button("Replace") { save() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("There's already a saved head with this name.")
        }
    }

    private var trimmedName: String { name.trimmingCharacters(in: .whitespacesAndNewlines) }

    private func trySave() {
        nameFocused = false
        if heads.exists(named: trimmedName) {
            confirmingReplace = true
        } else {
            save()
        }
    }

    private func save() {
        do {
            try flow.save(named: trimmedName, to: heads)
        } catch {
            saveError = error.localizedDescription
        }
    }
}

// MARK: - 2j. Saved

private struct SavedScreen: View {
    let name: String
    let onStartHaircut: () -> Void
    let onDone: () -> Void

    var body: some View {
        VStack(spacing: 20) {
            Spacer()
            VStack(spacing: 14) {
                Image(systemName: "checkmark.seal.fill")
                    .font(.system(size: 56))
                    .foregroundStyle(Color.brand.primary)
                Text("Saved \(name)'s head")
                    .font(.title2.bold())
                    .foregroundStyle(Color.brand.navy)
                    .multilineTextAlignment(.center)
                Text("HairBarbot will use this head model to know where the cutter is.")
                    .font(.body)
                    .foregroundStyle(Color.brand.navy.opacity(0.75))
                    .multilineTextAlignment(.center)
            }
            .padding(28)
            .frame(maxWidth: .infinity)
            .background(Color.brand.warmWhite, in: RoundedRectangle(cornerRadius: BrandMetrics.cardRadius))
            Spacer()
            Button("Start Haircut", action: onStartHaircut)
                .buttonStyle(.brandPrimary)
            Button("Done", action: onDone)
                .buttonStyle(.brandSecondary)
        }
        .padding(16)
    }
}

// MARK: - Shared layout for the text steps

/// Title, subtitle, scrolling content, and one primary button at the bottom.
private struct StepLayout<Content: View>: View {
    let title: String
    let subtitle: String
    let buttonTitle: String
    let action: () -> Void
    @ViewBuilder var content: () -> Content

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Text(title)
                        .font(.largeTitle.bold())
                        .foregroundStyle(Color.brand.ink)
                    Text(subtitle)
                        .font(.body)
                        .foregroundStyle(Color.brand.muted)
                        .fixedSize(horizontal: false, vertical: true)
                    content()
                }
                .padding(16)
            }
            Button(buttonTitle, action: action)
                .buttonStyle(.brandPrimary)
                .padding(16)
        }
    }
}
