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
                    Text("Tap the round button to start (3-2-1 countdown), and again to finish. Then tap Save.")
                }

                Section("Saved scans (\(store.scans.count))") {
                    if store.scans.isEmpty {
                        Text("No scans yet.")
                            .foregroundStyle(.secondary)
                    }
                    ForEach(store.scans) { scan in
                        row(for: scan)
                    }
                    .onDelete { offsets in
                        for index in offsets { store.delete(store.scans[index]) }
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
    }

    /// One saved scan: tap to view in 3D, share button to AirDrop, swipe to delete.
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

/// Shows StandardCyborg's scanning screen, then their 3D preview with Rescan / Save.
struct ScanningScreen: UIViewControllerRepresentable {
    let store: ScanStore
    /// Called when the person is finished (cancel, or after saving).
    let onClose: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(store: store, onClose: onClose)
    }

    func makeUIViewController(context: Context) -> ScanningViewController {
        let scanner = ScanningViewController()
        scanner.delegate = context.coordinator
        scanner.generatesTexturedMeshes = true  // color the 3D preview, like the example app
        return scanner
    }

    func updateUIViewController(_ scanner: ScanningViewController, context: Context) {}

    /// Receives messages from the scanning screen ("cancelled", "here is the scan").
    final class Coordinator: NSObject, ScanningViewControllerDelegate {
        let store: ScanStore
        let onClose: () -> Void

        init(store: ScanStore, onClose: @escaping () -> Void) {
            self.store = store
            self.onClose = onClose
        }

        // The X button on the scanning screen.
        func scanningViewControllerDidCancel(_ controller: ScanningViewController) {
            onClose()
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

            // Rescan: close the preview; the scanner restarts its camera when it reappears.
            preview.leftButton.addAction(UIAction { [weak controller] _ in
                controller?.dismiss(animated: false)
            }, for: .touchUpInside)

            // Save: write the scan to a PLY file, then go back to the Scan tab.
            preview.rightButton.addAction(UIAction { [weak self, weak preview] _ in
                guard let self else { return }
                do {
                    try self.store.save(pointCloud)
                    self.onClose()
                } catch {
                    let alert = UIAlertController(title: "Save failed",
                                                  message: error.localizedDescription,
                                                  preferredStyle: .alert)
                    alert.addAction(UIAlertAction(title: "OK", style: .default))
                    preview?.present(alert, animated: true)
                }
            }, for: .touchUpInside)

            // Full screen, so the scanner gets told when it is visible again (for Rescan).
            preview.modalPresentationStyle = .fullScreen
            controller.present(preview, animated: false)
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
