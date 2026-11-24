//
//  MergeView.swift
//  BarBot
//
//  Merging partial scans of the same object into one.
//
//  - MergeSheet: pick scans in order, then run the merge in the background.
//  - Merger (Shared/Merger.swift): does the work.
//  - MergeResultScreen: shows the merged scan in 3D with the numbers for each
//    step, and lets you save it.
//

import SwiftUI
import UIKit
import StandardCyborgFusion
import StandardCyborgUI

// MARK: - Picking scans

struct MergeSheet: View {
    let store: ScanStore
    /// Called with the finished merge (the sheet then closes itself).
    let onMerged: (MergeOutcome) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var picked: [SavedScan] = []
    /// Scans 2+ began from the same view as scan 1 (phone on a stand, person facing it).
    @AppStorage("mergeSameView") private var sameView = false
    @State private var status: String?
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ForEach(store.scans) { scan in
                        Button {
                            toggle(scan)
                        } label: {
                            HStack {
                                orderBadge(for: scan)
                                Text(scan.name)
                                    .font(.body.monospacedDigit())
                                Spacer()
                                Text(scan.date.formatted(date: .omitted, time: .shortened))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .tint(.primary)
                    }
                } footer: {
                    Text("Tap scans in order. Scan 1 stays put; each next scan is lined up onto the ones before it. Neighboring scans should overlap by about a third.")
                }

                Section {
                    Toggle("Started from the same view", isOn: $sameView)
                } footer: {
                    Text("On: every scan began facing a phone that didn't move (on a stand), so start lining up from where they were recorded (±25°). Off: search every turn.")
                }

                if let errorMessage {
                    Section {
                        Text(errorMessage).foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("Merge Scans")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                        .disabled(status != nil)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Merge \(picked.count)") { runMerge() }
                        .disabled(picked.count < 2 || status != nil)
                }
            }
            .overlay {
                if let status {
                    VStack(spacing: 12) {
                        ProgressView()
                        Text(status)
                    }
                    .padding(24)
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
                }
            }
            .interactiveDismissDisabled(status != nil)
        }
    }

    private func orderBadge(for scan: SavedScan) -> some View {
        Group {
            if let index = picked.firstIndex(of: scan) {
                Text("\(index + 1)")
                    .font(.caption.bold())
                    .foregroundStyle(.white)
                    .frame(width: 24, height: 24)
                    .background(Circle().fill(.blue))
            } else {
                Circle()
                    .strokeBorder(.secondary, lineWidth: 1.5)
                    .frame(width: 24, height: 24)
            }
        }
    }

    private func toggle(_ scan: SavedScan) {
        if let index = picked.firstIndex(of: scan) {
            picked.remove(at: index)
        } else {
            picked.append(scan)
        }
    }

    private func runMerge() {
        let scans = picked
        let first = picked.first
        let sameView = sameView
        errorMessage = nil
        status = "Starting…"
        Task {
            do {
                let outcome = try await Task.detached(priority: .userInitiated) {
                    try await Merger.merge(scans, startsFromSameView: { sameView && $0 != first }) { message in
                        await MainActor.run { status = message }
                    }
                }.value
                status = nil
                onMerged(outcome)
                dismiss()
            } catch {
                status = nil
                errorMessage = error.localizedDescription
            }
        }
    }
}

// MARK: - Showing the result

struct MergeResultScreen: View {
    let outcome: MergeOutcome
    let store: ScanStore
    let onClose: () -> Void

    @State private var saveError: String?

    var body: some View {
        MergePreview(pointCloud: outcome.pointCloud,
                     onDiscard: onClose,
                     onSave: save)
            .ignoresSafeArea()
            .overlay(alignment: .top) { report }
            .alert("Save failed", isPresented: Binding(get: { saveError != nil },
                                                       set: { if !$0 { saveError = nil } })) {
                Button("OK") { saveError = nil }
            } message: {
                Text(saveError ?? "")
            }
    }

    /// One line per merge step: overlap %, fit (mm), chosen turn, and the runner-up.
    private var report: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Base: \(outcome.baseScanName)")
            ForEach(Array(outcome.steps.enumerated()), id: \.element.id) { index, step in
                Text(line(for: step, number: index + 2))
                    .foregroundStyle(step.looksDoubtful ? .orange : .primary)
            }
            Text(String(format: "%.1f s", outcome.seconds))
                .foregroundStyle(.secondary)
        }
        .font(.caption.monospacedDigit())
        .padding(10)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 10))
        .padding(.top, 60)
        .padding(.horizontal, 12)
    }

    private func line(for step: MergeStepReport, number: Int) -> String {
        var text = String(format: "%d: overlap %.0f%%  see-through %.1f%%  fit %.1f mm  turn %.0f°",
                          number, step.overlap * 100, step.seeThrough * 100, step.fitMillimeters, step.yawDegrees)
        text += step.usedRecordedPose ? "  [from recorded pose]" : "  [full search]"
        if step.runnerUpOverlap > 0 {
            text += String(format: "\n    score %.2f, next %.0f°: score %.2f (overlap %.0f%%)",
                           step.score, step.runnerUpYawDegrees, step.runnerUpScore, step.runnerUpOverlap * 100)
        }
        if step.isAmbiguous { text += "  ⚠︎ unsure" }
        text += "\n    neck cut: " + cutText(step.scanCutCentimeters) + " / base " + cutText(step.baseCutCentimeters)
        return text
    }

    /// "24 cm" below the top of the head, or "none" if no neck was found.
    private func cutText(_ centimeters: Float) -> String {
        centimeters > 0 ? String(format: "%.0f cm", centimeters) : "none"
    }

    private func save() {
        do {
            try store.save(outcome.pointCloud, prefix: "merged")
            onClose()
        } catch {
            saveError = error.localizedDescription
        }
    }
}

/// StandardCyborg's 3D preview with Discard / Save buttons.
struct MergePreview: UIViewControllerRepresentable {
    let pointCloud: SCPointCloud
    let onDiscard: () -> Void
    let onSave: () -> Void

    func makeUIViewController(context: Context) -> ScenePreviewViewController {
        let preview = ScenePreviewViewController(pointCloud: pointCloud, meshTexturing: nil, landmarks: nil)
        preview.leftButton.setTitle("Discard", for: .normal)
        preview.leftButton.backgroundColor = .systemRed
        preview.rightButton.setTitle("Save", for: .normal)
        preview.rightButton.backgroundColor = .systemGreen
        preview.leftButton.addAction(UIAction { _ in onDiscard() }, for: .touchUpInside)
        preview.rightButton.addAction(UIAction { _ in onSave() }, for: .touchUpInside)
        return preview
    }

    func updateUIViewController(_ preview: ScenePreviewViewController, context: Context) {}
}
