//
//  ScanView.swift
//  BarBot
//
//  The Scan tab. For now it shows StandardCyborg's own scanning screen,
//  unchanged, then their 3D preview of the result.
//
//  StandardCyborg's screens are built with UIKit (Apple's older UI system),
//  so ScanningScreen below is a small adapter that lets SwiftUI show them.
//

import SwiftUI
import UIKit
import StandardCyborgFusion
import StandardCyborgUI

struct ScanView: View {
    @State private var isScanning = false

    var body: some View {
        VStack(spacing: 20) {
            Spacer()
            Image(systemName: "cube.transparent")
                .font(.system(size: 64))
                .foregroundStyle(.secondary)
            Text("3D Scan")
                .font(.title)
            Text("Tap the round button to start (3-2-1 countdown).\nTap it again to finish.")
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
            Spacer()
            Button {
                isScanning = true
            } label: {
                Label("Start Scan", systemImage: "viewfinder")
                    .font(.title2)
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
        }
        .padding()
        .fullScreenCover(isPresented: $isScanning) {
            ScanningScreen(onClose: { isScanning = false })
                .ignoresSafeArea()
        }
    }
}

/// Adapter: shows StandardCyborg's ScanningViewController inside SwiftUI.
struct ScanningScreen: UIViewControllerRepresentable {
    /// Called when the person is finished (cancel, or Done on the preview).
    let onClose: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onClose: onClose)
    }

    func makeUIViewController(context: Context) -> ScanningViewController {
        let scanner = ScanningViewController()
        scanner.delegate = context.coordinator
        scanner.generatesTexturedMeshes = true  // color the 3D result, like the example app
        return scanner
    }

    func updateUIViewController(_ scanner: ScanningViewController, context: Context) {}

    /// Receives messages from the scanning screen ("cancelled", "here is the scan").
    final class Coordinator: NSObject, ScanningViewControllerDelegate {
        let onClose: () -> Void

        init(onClose: @escaping () -> Void) {
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
            preview.rightButton.setTitle("Done", for: .normal)
            preview.rightButton.backgroundColor = .systemBlue

            // Rescan: close the preview; the scanner restarts its camera when it reappears.
            preview.leftButton.addAction(UIAction { [weak controller] _ in
                controller?.dismiss(animated: false)
            }, for: .touchUpInside)
            // Done: close everything and go back to the Scan tab.
            preview.rightButton.addAction(UIAction { [weak self] _ in
                self?.onClose()
            }, for: .touchUpInside)

            // Full screen, so the scanner gets told when it is visible again (for Rescan).
            preview.modalPresentationStyle = .fullScreen
            controller.present(preview, animated: false)
        }
    }
}
