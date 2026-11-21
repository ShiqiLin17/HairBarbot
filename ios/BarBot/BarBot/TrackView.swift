//
//  TrackView.swift
//  BarBot
//
//  The Track tab: Apple's face tracking (ARKit) on the front 3D camera.
//  Shows the camera picture with Apple's face mask drawn on it, and the live
//  head pose relative to the phone.
//
//  "Phone space" (all poses here are measured in it), with the phone upright
//  (portrait) and you looking at the screen:
//    x = toward the right edge of the screen (as the mirrored picture shows it)
//    y = toward the top of the phone
//    z = out of the screen, toward you. Your face is at negative z.
//
//  The front camera is used by one screen at a time, so this tab starts face
//  tracking when it appears and stops it when you leave.
//

import ARKit
import SceneKit
import SwiftUI

// MARK: - Pose

/// A head pose in phone space.
struct HeadPose {
    /// 4×4 transform from face space (Apple's face anchor) to phone space.
    var transform: simd_float4x4

    var position: SIMD3<Float> { SIMD3(transform.columns.3.x, transform.columns.3.y, transform.columns.3.z) }

    /// Turn, nod and tilt in degrees, for a face looking at the phone (all 0).
    /// Order: turn about up (y), then nod about sideways (x), then tilt about forward (z).
    /// turn > 0: face points toward the screen's right edge.
    /// nod  > 0: face points down.
    /// tilt > 0: head leans toward the screen's left edge.
    var angles: (turn: Float, nod: Float, tilt: Float) {
        let m = transform
        let nod = asin(max(-1, min(1, -m.columns.2.y)))
        let turn = atan2(m.columns.2.x, m.columns.2.z)
        let tilt = atan2(m.columns.0.y, m.columns.1.y)
        let degrees: Float = 180 / .pi
        return (turn * degrees, nod * degrees, tilt * degrees)
    }
}

/// What the Track tab shows, updated from face tracking.
@Observable
final class TrackState {
    enum Status: Equatable {
        case starting
        case unsupported
        case noFace
        case tracking
        case failed(String)
    }

    var status: Status = .starting
    var pose: HeadPose?
    /// Face updates per second (Apple's tracking aims for 60).
    var updatesPerSecond: Double = 0
    var showMask = true

    // For the rate counter
    fileprivate var updateCount = 0
    fileprivate var countStart = Date()
}

// MARK: - Screen

struct TrackView: View {
    @State private var state = TrackState()
    @State private var isVisible = false

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            if state.status == .unsupported {
                Text("This phone doesn't support face tracking.")
                    .foregroundStyle(.white)
                    .padding()
            } else if isVisible {
                FaceTrackingView(state: state)
                    .ignoresSafeArea()
            }
            VStack {
                readout
                    .padding(.horizontal)
                Spacer()
                Toggle("Show face mask", isOn: $state.showMask)
                    .toggleStyle(.button)
                    .padding(.bottom, 24)
            }
        }
        .onAppear {
            if !ARFaceTrackingConfiguration.isSupported { state.status = .unsupported }
            isVisible = true
        }
        .onDisappear {
            // Removing the view pauses face tracking and frees the camera.
            isVisible = false
            state.pose = nil
            state.status = .starting
        }
    }

    private var readout: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Circle()
                    .fill(statusColor)
                    .frame(width: 10, height: 10)
                Text(statusText).bold()
                Spacer()
                Text(String(format: "%.0f /s", state.updatesPerSecond))
                    .foregroundStyle(.secondary)
            }
            if let pose = state.pose, state.status == .tracking {
                let a = pose.angles
                let p = pose.position * 100
                Text(String(format: "turn %+6.1f°   nod %+6.1f°   tilt %+6.1f°", a.turn, a.nod, a.tilt))
                Text(String(format: "x %+5.1f cm   y %+5.1f cm   distance %4.1f cm", p.x, p.y, -p.z))
                    .foregroundStyle(.secondary)
            } else {
                Text("turn —   nod —   tilt —")
                Text("x —   y —   distance —")
                    .foregroundStyle(.secondary)
            }
        }
        .font(.callout.monospacedDigit())
        .padding(12)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }

    private var statusColor: Color {
        switch state.status {
        case .tracking: .green
        case .noFace, .starting: .yellow
        case .unsupported, .failed: .red
        }
    }

    private var statusText: String {
        switch state.status {
        case .starting: "Starting…"
        case .unsupported: "Not supported"
        case .noFace: "No face found"
        case .tracking: "Tracking"
        case .failed(let reason): "Stopped: \(reason)"
        }
    }
}

// MARK: - ARKit view

/// Apple's AR view, running face tracking, with the face mask drawn on the face.
struct FaceTrackingView: UIViewRepresentable {
    let state: TrackState

    func makeCoordinator() -> Coordinator { Coordinator(state: state) }

    func makeUIView(context: Context) -> ARSCNView {
        let view = ARSCNView()
        view.delegate = context.coordinator
        view.session.delegate = context.coordinator
        view.automaticallyUpdatesLighting = true

        let configuration = ARFaceTrackingConfiguration()
        configuration.worldAlignment = .camera   // poses relative to the phone, not the room
        configuration.isLightEstimationEnabled = false
        view.session.run(configuration, options: [.resetTracking, .removeExistingAnchors])
        return view
    }

    func updateUIView(_ view: ARSCNView, context: Context) {
        context.coordinator.maskVisible = state.showMask
    }

    static func dismantleUIView(_ view: ARSCNView, coordinator: Coordinator) {
        view.session.pause()
    }

    final class Coordinator: NSObject, ARSCNViewDelegate, ARSessionDelegate {
        let state: TrackState
        /// Read by SceneKit's drawing thread.
        nonisolated(unsafe) var maskVisible = true

        init(state: TrackState) { self.state = state }

        // Called on the main thread (the session's default delegate queue).
        nonisolated func session(_ session: ARSession, didUpdate frame: ARFrame) {
            // Head pose in phone space: Apple's face pose, seen from the phone held upright.
            let face = frame.anchors.compactMap { $0 as? ARFaceAnchor }.first
            let tracked = face?.isTracked == true
            let transform = face.map { frame.camera.viewMatrix(for: .portrait) * $0.transform }
            MainActor.assumeIsolated {
                if tracked, let transform {
                    state.status = .tracking
                    state.pose = HeadPose(transform: transform)
                    state.updateCount += 1
                } else if state.status != .unsupported {
                    state.status = .noFace
                }
                let elapsed = Date().timeIntervalSince(state.countStart)
                if elapsed >= 1 {
                    state.updatesPerSecond = Double(state.updateCount) / elapsed
                    state.updateCount = 0
                    state.countStart = Date()
                }
            }
        }

        nonisolated func session(_ session: ARSession, didFailWithError error: Error) {
            let message = error.localizedDescription
            MainActor.assumeIsolated { state.status = .failed(message) }
        }

        // Called on SceneKit's drawing thread: the face mask as white lines.
        nonisolated func renderer(_ renderer: SCNSceneRenderer, nodeFor anchor: ARAnchor) -> SCNNode? {
            guard anchor is ARFaceAnchor,
                  let device = renderer.device,
                  let geometry = ARSCNFaceGeometry(device: device) else { return nil }
            let material = geometry.firstMaterial
            material?.fillMode = .lines
            material?.diffuse.contents = UIColor.white.withAlphaComponent(0.8)
            material?.lightingModel = .constant
            return SCNNode(geometry: geometry)
        }

        nonisolated func renderer(_ renderer: SCNSceneRenderer, didUpdate node: SCNNode, for anchor: ARAnchor) {
            guard let face = anchor as? ARFaceAnchor,
                  let geometry = node.geometry as? ARSCNFaceGeometry else { return }
            geometry.update(from: face.geometry)
            node.isHidden = !maskVisible
        }
    }
}
