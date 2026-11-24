//
//  GuidedScanView.swift
//  HairBarbot
//
//  One scan pass (right, left or top): StandardCyborg's scanner with its own
//  buttons hidden, plus our instructions, a spoken 5-second countdown, a
//  tracking border, sounds, and a chime + voice when the scan ends.
//
//  The scan ends by itself when the scanner loses track of the head (it has
//  turned as far as the camera can follow). "Finish Scan" ends it by hand.
//

import SwiftUI
import UIKit
import StandardCyborgFusion
import StandardCyborgUI

struct GuidedScanView: View {
    let pass: ScanPass
    let flow: ScanFlow
    let sounds: ScanSounds

    private enum Phase: Equatable {
        case ready
        case countdown(Int)
        case scanning
        case finishing
        case tooShort

        var isCountdown: Bool {
            if case .countdown = self { return true }
            return false
        }
    }

    @State private var phase: Phase = .ready
    @State private var quality: ScanTrackingQuality = .good
    @State private var control = ScannerControl()
    @State private var countdownTask: Task<Void, Never>?
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack {
            GuidedScannerController(control: control)
                .ignoresSafeArea()

            if phase == .ready || phase.isCountdown {
                HeadGuide()
                    .allowsHitTesting(false)
            }

            if phase == .scanning {
                Rectangle()
                    .strokeBorder(trackingColor, lineWidth: 14)
                    .ignoresSafeArea()
                    .allowsHitTesting(false)
                    .animation(reduceMotion ? nil : .easeOut(duration: 0.15), value: quality)
            }

            if case .countdown(let seconds) = phase {
                Text("\(seconds)")
                    .font(.system(size: 120, weight: .semibold, design: .rounded).monospacedDigit())
                    .foregroundStyle(Color.brand.warmWhite)
                    .shadow(radius: 6)
                    .accessibilityLabel("Starting in \(seconds)")
            }

            VStack {
                if phase == .scanning {
                    statusPill.padding(.top, 70)
                }
                Spacer()
                bottomPanel
                    .padding(.horizontal, 16)
                    .padding(.bottom, 24)
            }
        }
        .onAppear(perform: wireUp)
        .onDisappear {
            countdownTask?.cancel()
            if phase == .scanning {
                phase = .ready   // so the cancel below isn't reported as "too short"
                control.scanner?.stopScanning(reason: .canceled)
            }
        }
    }

    // MARK: - Pieces

    @ViewBuilder
    private var bottomPanel: some View {
        switch phase {
        case .ready:
            VStack(alignment: .leading, spacing: 14) {
                Text(title)
                    .font(.title2.bold())
                    .foregroundStyle(Color.brand.ink)
                Text(instructions)
                    .font(.body)
                    .foregroundStyle(Color.brand.muted)
                    .fixedSize(horizontal: false, vertical: true)
                Button("Start", action: startCountdown)
                    .buttonStyle(.brandPrimary)
            }
            .brandCard(padding: 20)

        case .countdown:
            Button("Cancel") {
                countdownTask?.cancel()
                phase = .ready
            }
            .buttonStyle(.brandSecondary)

        case .scanning:
            Button("Finish Scan") {
                control.scanner?.stopScanning(reason: .finished)
            }
            .buttonStyle(.brandSecondary)

        case .finishing:
            HStack(spacing: 12) {
                ProgressView()
                Text("Finishing the scan…")
                    .font(.headline)
                    .foregroundStyle(Color.brand.ink)
            }
            .brandCard(padding: 20)

        case .tooShort:
            VStack(alignment: .leading, spacing: 14) {
                Label("That scan was too short", systemImage: "tortoise")
                    .font(.title3.bold())
                    .foregroundStyle(Color.brand.ink)
                Text("The scanner lost its place almost right away. Try again and move a bit more slowly.")
                    .font(.body)
                    .foregroundStyle(Color.brand.muted)
                    .fixedSize(horizontal: false, vertical: true)
                Button("Try Again") { phase = .ready }
                    .buttonStyle(.brandPrimary)
            }
            .brandCard(padding: 20)
        }
    }

    private var statusPill: some View {
        Label(quality == .good ? "Keep going slowly" : "Slow down",
              systemImage: quality == .good ? "checkmark" : "tortoise.fill")
            .font(.headline)
            .foregroundStyle(Color.brand.onPrimary)
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(trackingColor, in: Capsule())
    }

    /// Brand blue while tracking is good, amber ("adjust") when it's struggling.
    private var trackingColor: Color {
        quality == .good ? Color.brand.primary : Color.brand.warn
    }

    private var title: String {
        switch pass {
        case .right: "Scan 1: right side"
        case .left: "Scan 2: left side"
        case .top: "Scan 3: top of the head"
        }
    }

    private var instructions: String {
        switch pass {
        case .right:
            "Face the phone and stand still. After the countdown, turn slowly to your right until the sounds stop."
        case .left:
            "Face the phone again and stand still. After the countdown, turn slowly to your left until the sounds stop."
        case .top:
            "Take the phone off the stand and hold it in front of the face at arm's length. After the countdown, slowly raise it in an arc, up and over, until it looks straight down at the top of the head. The sounds stop when it's done."
        }
    }

    private var goPrompt: String {
        switch pass {
        case .right: "Turn right, slowly."
        case .left: "Turn left, slowly."
        case .top: "Raise the phone up and over, slowly."
        }
    }

    // MARK: - Actions

    private func startCountdown() {
        sounds.say("Get ready.")
        countdownTask = Task {
            for seconds in stride(from: 5, through: 1, by: -1) {
                phase = .countdown(seconds)
                if seconds <= 3 { sounds.say("\(seconds)") }
                try? await Task.sleep(for: .seconds(1))
                if Task.isCancelled { return }
            }
            control.scanner?.startScanning()
        }
    }

    private func wireUp() {
        control.onStart = {
            quality = .good
            phase = .scanning
            sounds.say(goPrompt)
        }
        control.onQuality = { newQuality in
            if newQuality != quality { quality = newQuality }
            sounds.update(newQuality)
        }
        control.onStop = { reason, _ in
            if reason == .finished {
                phase = .finishing
                sounds.playDone()
                Task {
                    try? await Task.sleep(for: .milliseconds(600))
                    sounds.say("Scan done. Come back to the phone.")
                }
            } else if phase == .scanning {
                phase = .tooShort
                sounds.say("That was too short. Let's try again, a bit more slowly.")
            }
        }
        control.onScan = { pointCloud in
            flow.captured(pointCloud, for: pass)
        }
    }
}

/// A dashed oval where the head should be.
private struct HeadGuide: View {
    var body: some View {
        GeometryReader { geometry in
            let width = geometry.size.width * 0.62
            Ellipse()
                .stroke(Color.brand.warmWhite.opacity(0.8), style: StrokeStyle(lineWidth: 3, dash: [10, 8]))
                .frame(width: width, height: width * 1.3)
                .position(x: geometry.size.width / 2, y: geometry.size.height * 0.4)
        }
        .accessibilityHidden(true)
    }
}

// MARK: - StandardCyborg scanner adapter

/// Receives the scanner's messages and passes them on to the SwiftUI screen.
final class ScannerControl: NSObject, ScanningViewControllerDelegate {
    weak var scanner: ScanningViewController?
    var onStart: () -> Void = {}
    var onQuality: (ScanTrackingQuality) -> Void = { _ in }
    var onStop: (ScanningViewController.ScanningTerminationReason, Bool) -> Void = { _, _ in }
    var onScan: (SCPointCloud) -> Void = { _ in }

    // Its own close button is hidden; the flow's X handles cancelling.
    func scanningViewControllerDidCancel(_ controller: ScanningViewController) {}

    func scanningViewControllerDidStartScanning(_ controller: ScanningViewController) {
        onStart()
    }

    func scanningViewController(_ controller: ScanningViewController,
                                didUpdateTracking quality: ScanTrackingQuality,
                                framesCaptured: Int) {
        onQuality(quality)
    }

    func scanningViewController(_ controller: ScanningViewController,
                                didStopScanningWith reason: ScanningViewController.ScanningTerminationReason,
                                trackingLost: Bool) {
        onStop(reason, trackingLost)
    }

    func scanningViewController(_ controller: ScanningViewController, didScan pointCloud: SCPointCloud) {
        onScan(pointCloud)
    }
}

/// StandardCyborg's ScanningViewController (UIKit) inside SwiftUI, without its buttons.
struct GuidedScannerController: UIViewControllerRepresentable {
    let control: ScannerControl

    func makeUIViewController(context: Context) -> ScanningViewController {
        let scanner = ScanningViewController()
        scanner.delegate = control
        scanner.countdownStartCount = 0      // we run our own spoken countdown
        scanner.shutterButton.isHidden = true
        scanner.dismissButton.isHidden = true
        control.scanner = scanner
        return scanner
    }

    func updateUIViewController(_ scanner: ScanningViewController, context: Context) {}
}
