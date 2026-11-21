//
//  ScanView.swift
//  BarBot
//
//  The Scan tab: start a scan, and see / share / delete saved scans.
//
//  Scanning uses StandardCyborg's own screens (unchanged for now).
//  They are built with UIKit (Apple's older UI system), so the small
//  "adapter" structs at the bottom let SwiftUI show them.
//

import SwiftUI
import UIKit
import StandardCyborgFusion
import StandardCyborgUI

struct ScanView: View {
    @State private var store = ScanStore()
    @State private var isScanning = false
    @State private var viewing: SavedScan?
    @State private var showingMergeSheet = false
    @State private var pendingMerge: MergeOutcome?
    @State private var mergeResult: MergeOutcome?
    @State private var renaming: SavedScan?
    @State private var newName = ""
    @State private var renameError: String?
    @State private var fitting: SavedScan?

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Button {
                        isScanning = true
                    } label: {
                        Label("Start Scan", systemImage: "viewfinder")
                            .font(.title2)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 8)
                    }
                    .buttonStyle(.borderedProminent)
                    .listRowBackground(Color.clear)
                    .listRowInsets(EdgeInsets())
                } footer: {
                    Text("Tap the round button to start (2-1 countdown), and again to finish. Then tap Save.")
                }

                Section("Saved scans (\(store.scans.count))") {
                    if store.scans.isEmpty {
                        Text("No scans yet.")
                            .foregroundStyle(.secondary)
                    }
                    ForEach(store.scans) { scan in
                        row(for: scan)
                            // Swipe left: Delete / Rename
                            .swipeActions(edge: .trailing) {
                                Button(role: .destructive) {
                                    store.delete(scan)
                                } label: {
                                    Label("Delete", systemImage: "trash")
                                }
                                Button {
                                    startRenaming(scan)
                                } label: {
                                    Label("Rename", systemImage: "pencil")
                                }
                                .tint(.blue)
                            }
                            // Long-press: the same, plus Share and Fit Head Model
                            .contextMenu {
                                Button {
                                    fitting = scan
                                } label: {
                                    Label("Fit Head Model", systemImage: "person.crop.circle")
                                }
                                Button {
                                    startRenaming(scan)
                                } label: {
                                    Label("Rename", systemImage: "pencil")
                                }
                                ShareLink(item: scan.url)
                                Button(role: .destructive) {
                                    store.delete(scan)
                                } label: {
                                    Label("Delete", systemImage: "trash")
                                }
                            }
                    }
                }
            }
            .navigationTitle("Scan")
            .refreshable { store.reload() }
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button {
                        showingMergeSheet = true
                    } label: {
                        Label("Merge", systemImage: "square.on.square")
                    }
                    .disabled(store.scans.count < 2)
                }
            }
        }
        .sheet(isPresented: $showingMergeSheet, onDismiss: {
            // Show the result once the picker sheet has fully closed
            if let outcome = pendingMerge {
                pendingMerge = nil
                mergeResult = outcome
            }
        }) {
            MergeSheet(store: store, onMerged: { pendingMerge = $0 })
        }
        .fullScreenCover(item: $mergeResult) { outcome in
            MergeResultScreen(outcome: outcome, store: store, onClose: { mergeResult = nil })
        }
        .fullScreenCover(isPresented: $isScanning) {
            ScanningScreen(store: store, onClose: { isScanning = false })
                .ignoresSafeArea()
        }
        .fullScreenCover(item: $viewing) { scan in
            SavedScanScreen(scan: scan, store: store, onClose: { viewing = nil })
                .ignoresSafeArea()
        }
        .fullScreenCover(item: $fitting) { scan in
            HeadFitScreen(scan: scan, store: store, onClose: { fitting = nil })
        }
        // Rename: a box to type the new name
        .alert("Rename Scan", isPresented: Binding(get: { renaming != nil },
                                                   set: { if !$0 { renaming = nil } })) {
            TextField("Name", text: $newName)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
            Button("Rename") { finishRenaming() }
            Button("Cancel", role: .cancel) { renaming = nil }
        } message: {
            Text("e.g. bryson-front-cap")
        }
        .alert("Couldn't Rename", isPresented: Binding(get: { renameError != nil },
                                                      set: { if !$0 { renameError = nil } })) {
            Button("OK") { renameError = nil }
        } message: {
            Text(renameError ?? "")
        }
    }

    private func startRenaming(_ scan: SavedScan) {
        newName = scan.name
        renaming = scan
    }

    private func finishRenaming() {
        guard let scan = renaming else { return }
        renaming = nil
        do {
            try store.rename(scan, to: newName)
        } catch {
            renameError = error.localizedDescription
        }
    }

    /// One saved scan: tap to view in 3D, share button to AirDrop,
    /// swipe left or long-press to rename or delete.
    private func row(for scan: SavedScan) -> some View {
        HStack {
            Button {
                viewing = scan
            } label: {
                VStack(alignment: .leading, spacing: 2) {
                    Text(scan.name)
                        .font(.body.monospacedDigit())
                    Text("\(scan.date.formatted(date: .abbreviated, time: .shortened)) · \(scan.sizeBytes.formatted(.byteCount(style: .file)))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .tint(.primary)
            Spacer()
            ShareLink(item: scan.url) {
                Image(systemName: "square.and.arrow.up")
            }
            .buttonStyle(.borderless)
        }
    }
}

// MARK: - Adapters for StandardCyborg's UIKit screens

/// What's happening during a scan, for the border / timer / message overlay.
@Observable
final class ScanSession {
    var isScanning = false
    var startedAt = Date()
    var quality: ScanTrackingQuality = .good
    var framesCaptured = 0
    /// Shown after a scan stops on its own (e.g. tracking lost).
    var message: String?
}

/// The scanning screen: StandardCyborg's scanner, plus a colored tracking border,
/// a recording timer, sounds, and a message when a scan stops on its own.
struct ScanningScreen: View {
    let store: ScanStore
    /// Called when the person is finished (cancel, or after saving).
    let onClose: () -> Void

    @State private var session = ScanSession()
    @State private var sounds = ScanSounds()
    /// Remembered between scans and app launches.
    @AppStorage("scanSoundsOn") private var soundsOn = true

    var body: some View {
        ScannerController(store: store, session: session, sounds: sounds, onClose: onClose)
            .ignoresSafeArea()
            .overlay {
                // Thick border: green = good, yellow = poor, red = lost
                if session.isScanning {
                    Rectangle()
                        .strokeBorder(borderColor, lineWidth: 18)
                        .ignoresSafeArea()
                        .allowsHitTesting(false)
                        .animation(.easeOut(duration: 0.15), value: session.quality)
                }
            }
            .overlay(alignment: .top) {
                statusBar
                    .padding(.top, 56)
                    .allowsHitTesting(false)
            }
            .overlay(alignment: .topTrailing) {
                soundButton
                    .padding(.top, 104)
                    .padding(.trailing, 20)
            }
            .onAppear { sounds.isMuted = !soundsOn }
            .onChange(of: soundsOn) { _, on in sounds.isMuted = !on }
            .onDisappear { sounds.stop() }
    }

    /// Speaker button: turns the tracking sounds on or off (works mid-scan too).
    private var soundButton: some View {
        Button {
            soundsOn.toggle()
        } label: {
            Image(systemName: soundsOn ? "speaker.wave.2.fill" : "speaker.slash.fill")
                .font(.title2)
                .foregroundStyle(.white)
                .frame(width: 52, height: 52)
                .background(.black.opacity(0.5), in: Circle())
        }
        .accessibilityLabel(soundsOn ? "Turn sounds off" : "Turn sounds on")
    }

    private var borderColor: Color {
        switch session.quality {
        case .good: .green
        case .poor: .yellow
        case .lost: .red
        @unknown default: .red
        }
    }

    private var qualityText: String {
        switch session.quality {
        case .good: "Tracking good"
        case .poor: "Slow down"
        case .lost: "Lost — go back"
        @unknown default: "Lost"
        }
    }

    @ViewBuilder
    private var statusBar: some View {
        if session.isScanning {
            TimelineView(.periodic(from: session.startedAt, by: 0.1)) { context in
                let seconds = Int(context.date.timeIntervalSince(session.startedAt))
                Text("● \(seconds / 60):\(String(format: "%02d", seconds % 60))   \(session.framesCaptured) frames   \(qualityText)")
                    .font(.headline.monospacedDigit())
                    .foregroundStyle(.white)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 8)
                    .background(borderColor.opacity(0.85), in: Capsule())
            }
        } else if let message = session.message {
            Text(message)
                .font(.headline)
                .multilineTextAlignment(.center)
                .foregroundStyle(.white)
                .padding(12)
                .background(.red.opacity(0.85), in: RoundedRectangle(cornerRadius: 12))
                .padding(.horizontal, 24)
        }
    }
}

/// Adapter: StandardCyborg's ScanningViewController (UIKit) inside SwiftUI,
/// then their 3D preview with Rescan / Save.
struct ScannerController: UIViewControllerRepresentable {
    let store: ScanStore
    let session: ScanSession
    let sounds: ScanSounds
    let onClose: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(store: store, session: session, sounds: sounds, onClose: onClose)
    }

    func makeUIViewController(context: Context) -> ScanningViewController {
        let scanner = ScanningViewController()
        scanner.delegate = context.coordinator
        scanner.generatesTexturedMeshes = true  // color the 3D preview, like the example app
        scanner.countdownStartCount = 2         // 2-1, then scanning
        return scanner
    }

    func updateUIViewController(_ scanner: ScanningViewController, context: Context) {}

    /// Labels you can give a scan when saving (become part of the file name).
    static let labels = ["front", "left", "right", "back", "top"]

    /// Receives messages from the scanning screen.
    final class Coordinator: NSObject, ScanningViewControllerDelegate {
        let store: ScanStore
        let session: ScanSession
        let sounds: ScanSounds
        let onClose: () -> Void
        private var lastStopWasTrackingLoss = false

        init(store: ScanStore, session: ScanSession, sounds: ScanSounds, onClose: @escaping () -> Void) {
            self.store = store
            self.session = session
            self.sounds = sounds
            self.onClose = onClose
        }

        // The X button on the scanning screen.
        func scanningViewControllerDidCancel(_ controller: ScanningViewController) {
            sounds.stop()
            onClose()
        }

        func scanningViewControllerDidStartScanning(_ controller: ScanningViewController) {
            session.isScanning = true
            session.startedAt = Date()
            session.quality = .good
            session.framesCaptured = 0
            session.message = nil
            sounds.start()
        }

        func scanningViewController(_ controller: ScanningViewController,
                                    didUpdateTracking quality: ScanTrackingQuality,
                                    framesCaptured: Int) {
            session.quality = quality
            session.framesCaptured = framesCaptured
            sounds.update(quality)
        }

        func scanningViewController(_ controller: ScanningViewController,
                                    didStopScanningWith reason: ScanningViewController.ScanningTerminationReason,
                                    trackingLost: Bool) {
            session.isScanning = false
            sounds.stop()
            lastStopWasTrackingLoss = trackingLost
            if trackingLost && reason == .canceled {
                session.message = "Tracking lost after only \(session.framesCaptured) frames — too little to keep.\nMove slower and try again."
            }
        }

        // A scan finished: show StandardCyborg's 3D preview on top.
        func scanningViewController(_ controller: ScanningViewController, didScan pointCloud: SCPointCloud) {
            let preview = ScenePreviewViewController(pointCloud: pointCloud,
                                                     meshTexturing: controller.meshTexturing,
                                                     landmarks: nil)
            preview.leftButton.setTitle("Rescan", for: .normal)
            preview.leftButton.backgroundColor = .systemOrange
            preview.rightButton.setTitle("Save", for: .normal)
            preview.rightButton.backgroundColor = .systemGreen

            if lastStopWasTrackingLoss {
                addBanner("Tracking was lost — this is what was captured before that.", to: preview)
            }

            // Rescan: close the preview; the scanner restarts its camera when it reappears.
            preview.leftButton.addAction(UIAction { [weak controller] _ in
                controller?.dismiss(animated: false)
            }, for: .touchUpInside)

            // Save: pick a label (front / left / ...), write the PLY file, go back to the Scan tab.
            preview.rightButton.addAction(UIAction { [weak self, weak preview] _ in
                guard let self, let preview else { return }
                self.askForLabelAndSave(pointCloud, from: preview)
            }, for: .touchUpInside)

            // Full screen, so the scanner gets told when it is visible again (for Rescan).
            preview.modalPresentationStyle = .fullScreen
            controller.present(preview, animated: false)
        }

        private func askForLabelAndSave(_ pointCloud: SCPointCloud, from preview: UIViewController) {
            let sheet = UIAlertController(title: "Which side was scanned?",
                                          message: "The label is added to the file name, to help when merging.",
                                          preferredStyle: .actionSheet)
            for label in ScannerController.labels {
                sheet.addAction(UIAlertAction(title: label.capitalized, style: .default) { _ in
                    self.save(pointCloud, label: label, from: preview)
                })
            }
            sheet.addAction(UIAlertAction(title: "Custom name…", style: .default) { _ in
                self.askForNameAndSave(pointCloud, from: preview)
            })
            sheet.addAction(UIAlertAction(title: "No label", style: .default) { _ in
                self.save(pointCloud, label: nil, from: preview)
            })
            sheet.addAction(UIAlertAction(title: "Cancel", style: .cancel))
            preview.present(sheet, animated: true)
        }

        /// Asks for a name, then saves under it (asks again if it's empty or taken).
        private func askForNameAndSave(_ pointCloud: SCPointCloud, from preview: UIViewController,
                                       message: String = "e.g. bryson-front-cap") {
            let alert = UIAlertController(title: "Name this scan", message: message, preferredStyle: .alert)
            alert.addTextField { field in
                field.placeholder = "Name"
                field.autocorrectionType = .no
                field.autocapitalizationType = .none
                field.clearButtonMode = .whileEditing
            }
            alert.addAction(UIAlertAction(title: "Cancel", style: .cancel))
            alert.addAction(UIAlertAction(title: "Save", style: .default) { [weak alert] _ in
                let name = alert?.textFields?.first?.text ?? ""
                do {
                    try self.store.save(pointCloud, named: name)
                    self.onClose()
                } catch {
                    self.askForNameAndSave(pointCloud, from: preview, message: error.localizedDescription)
                }
            })
            preview.present(alert, animated: true)
        }

        private func save(_ pointCloud: SCPointCloud, label: String?, from preview: UIViewController) {
            do {
                try store.save(pointCloud, label: label)
                onClose()
            } catch {
                let alert = UIAlertController(title: "Save failed",
                                              message: error.localizedDescription,
                                              preferredStyle: .alert)
                alert.addAction(UIAlertAction(title: "OK", style: .default))
                preview.present(alert, animated: true)
            }
        }

        private func addBanner(_ text: String, to preview: UIViewController) {
            let label = UILabel()
            label.text = text
            label.numberOfLines = 0
            label.textAlignment = .center
            label.font = .preferredFont(forTextStyle: .headline)
            label.textColor = .white
            label.backgroundColor = UIColor.systemOrange.withAlphaComponent(0.9)
            label.layer.cornerRadius = 10
            label.clipsToBounds = true
            label.translatesAutoresizingMaskIntoConstraints = false
            preview.view.addSubview(label)
            NSLayoutConstraint.activate([
                label.topAnchor.constraint(equalTo: preview.view.safeAreaLayoutGuide.topAnchor, constant: 12),
                label.leadingAnchor.constraint(equalTo: preview.view.leadingAnchor, constant: 20),
                label.trailingAnchor.constraint(equalTo: preview.view.trailingAnchor, constant: -20),
                label.heightAnchor.constraint(greaterThanOrEqualToConstant: 56),
            ])
        }
    }
}

/// Opens a saved scan file in StandardCyborg's 3D preview.
struct SavedScanScreen: View {
    let scan: SavedScan
    let store: ScanStore
    let onClose: () -> Void

    var body: some View {
        if let pointCloud = store.load(scan) {
            SavedScanPreview(pointCloud: pointCloud, onClose: onClose)
                .overlay(alignment: .top) {
                    gravityLabel(pointCloud.gravity)
                }
        } else {
            VStack(spacing: 16) {
                Text("Couldn't open \(scan.name).")
                Button("Close", action: onClose)
                    .buttonStyle(.borderedProminent)
            }
        }
    }

    /// The scan's recorded gravity: which way "down" was when the scan started,
    /// in the phone's directions (x = right, y = up, z = toward you).
    /// Phone held upright facing the object ≈ (0.00, -1.00, 0.00).
    private func gravityLabel(_ g: SIMD3<Float>) -> some View {
        Text(String(format: "gravity  x %.2f   y %.2f   z %.2f", g.x, g.y, g.z))
            .font(.footnote.monospacedDigit())
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(.ultraThinMaterial, in: Capsule())
            .padding(.top, 60)
    }
}

struct SavedScanPreview: UIViewControllerRepresentable {
    let pointCloud: SCPointCloud
    let onClose: () -> Void

    func makeUIViewController(context: Context) -> ScenePreviewViewController {
        let preview = ScenePreviewViewController(pointCloud: pointCloud, meshTexturing: nil, landmarks: nil)
        preview.leftButton.isHidden = true
        preview.rightButton.setTitle("Close", for: .normal)
        preview.rightButton.backgroundColor = .systemBlue
        preview.rightButton.addAction(UIAction { _ in onClose() }, for: .touchUpInside)
        return preview
    }

    func updateUIViewController(_ preview: ScenePreviewViewController, context: Context) {}
}
