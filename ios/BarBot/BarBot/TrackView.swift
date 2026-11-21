//
//  TrackView.swift
//  BarBot
//
//  The Track tab: Apple's face tracking (ARKit) on the front 3D camera.
//  Shows the camera picture with Apple's face mask drawn on it, and the live
//  head pose relative to the phone. With a saved head chosen, "Line Up" snaps
//  Apple's mask onto that head's face (see LineUp.swift).
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

/// A pose in phone space.
struct HeadPose {
    /// 4×4 transform from the tracked thing's own space (Apple's face, or the head) to phone space.
    var transform: simd_float4x4

    var position: SIMD3<Float> { SIMD3(transform.columns.3.x, transform.columns.3.y, transform.columns.3.z) }

    /// Turn, nod and tilt in degrees, for a face looking at the phone (all 0).
    /// Order: turn about up (y), then nod about sideways (x), then tilt about forward (z).
    /// turn > 0: you turned to your right.
    /// nod  > 0: chin down.
    /// tilt > 0: left ear toward your shoulder.
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

    enum LineUpPhase: Equatable {
        case idle
        case countdown(Int)
        case collecting
        case computing
    }

    var status: Status = .starting
    /// Apple's face pose in phone space.
    var pose: HeadPose?
    /// Face updates per second (Apple's tracking aims for 60).
    var updatesPerSecond: Double = 0
    var showMask = true

    var lineUpPhase: LineUpPhase = .idle
    /// Set while collecting mask frames for a line-up.
    var collector: LineUpCollector?
    var collectProgress: Double = 0

    // For the rate counter
    fileprivate var updateCount = 0
    fileprivate var countStart = Date()
}

// MARK: - Screen

struct TrackView: View {
    @Environment(HeadStore.self) private var heads
    @AppStorage("trackHeadName") private var headName = ""
    @State private var state = TrackState()
    @State private var isVisible = false
    @State private var message: (title: String, text: String)?

    /// The chosen saved head (re-read from the store so a new line-up shows up).
    private var head: SavedHead? { heads.heads.first { $0.name == headName } }

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
                lineUpOverlay
                Spacer()
                controls
                    .padding(.horizontal)
                    .padding(.bottom, 12)
            }
        }
        .onAppear {
            if !ARFaceTrackingConfiguration.isSupported { state.status = .unsupported }
            if head == nil { headName = heads.heads.first?.name ?? "" }
            isVisible = true
        }
        .onDisappear {
            // Removing the view pauses face tracking and frees the camera.
            isVisible = false
            state.pose = nil
            state.status = .starting
            state.collector = nil
            state.lineUpPhase = .idle
        }
        .alert(message?.title ?? "", isPresented: Binding(get: { message != nil },
                                                          set: { if !$0 { message = nil } })) {
            Button("OK") { message = nil }
        } message: {
            Text(message?.text ?? "")
        }
    }

    // MARK: Pieces

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
            if let lineUp = head?.lineUp {
                Divider()
                Text(String(format: "line-up error %.1f mm   %d of %d points",
                            lineUp.rmsError * 1000, lineUp.usedPoints, lineUp.totalPoints))
                Text("lined up \(lineUp.created.formatted(date: .abbreviated, time: .shortened))"
                     + String(format: " · moved %.1f mm / %.1f°", lineUp.movedMillimeters, lineUp.movedDegrees))
                    .foregroundStyle(.secondary)
            }
        }
        .font(.callout.monospacedDigit())
        .padding(12)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }

    @ViewBuilder
    private var lineUpOverlay: some View {
        switch state.lineUpPhase {
        case .idle:
            EmptyView()
        case .countdown(let n):
            VStack(spacing: 8) {
                Text("Look straight at the phone.\nRelaxed face, mouth closed.")
                    .multilineTextAlignment(.center)
                Text("\(n)").font(.system(size: 64, weight: .bold).monospacedDigit())
            }
            .padding(24)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 16))
        case .collecting:
            VStack(spacing: 8) {
                Text("Hold still…")
                ProgressView(value: state.collectProgress)
                    .frame(width: 180)
            }
            .padding(24)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 16))
        case .computing:
            VStack(spacing: 8) {
                ProgressView()
                Text("Lining up…")
            }
            .padding(24)
            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 16))
        }
    }

    private var controls: some View {
        VStack(spacing: 10) {
            HStack {
                Menu {
                    if heads.heads.isEmpty {
                        Text("No saved heads. Fit a scan and Save → Use for Tracking.")
                    }
                    ForEach(heads.heads) { saved in
                        Button {
                            headName = saved.name
                        } label: {
                            if saved.name == headName {
                                Label(saved.name, systemImage: "checkmark")
                            } else {
                                Text(saved.name)
                            }
                        }
                    }
                } label: {
                    Label(head?.name ?? "Choose head", systemImage: "person.crop.circle")
                        .lineLimit(1)
                }
                .buttonStyle(.bordered)

                Spacer()

                Toggle("Mask", isOn: $state.showMask)
                    .toggleStyle(.button)
            }

            Button {
                startLineUp()
            } label: {
                Label(head?.lineUp == nil ? "Line Up" : "Line Up Again", systemImage: "scope")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(head == nil || state.status != .tracking || state.lineUpPhase != .idle)
        }
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

    // MARK: Line-up

    /// 3-2-1 countdown, collect about a second of mask frames, then snap them onto the head.
    private func startLineUp() {
        guard let head else { return }
        Task {
            for n in stride(from: 3, through: 1, by: -1) {
                state.lineUpPhase = .countdown(n)
                try? await Task.sleep(for: .seconds(1))
            }
            let collector = LineUpCollector()
            state.collectProgress = 0
            state.collector = collector
            state.lineUpPhase = .collecting
            // The tracking callback fills the collector; wait until it's full (or the face is lost).
            var waited = 0
            while !collector.isDone && waited < 300 {
                try? await Task.sleep(for: .milliseconds(20))
                waited += 1
                if state.collector !== collector { return }  // tab was left
            }
            state.collector = nil
            guard collector.isDone else {
                finish(title: "Line-Up Failed", text: "Your face wasn't tracked long enough. Try again facing the phone.")
                return
            }
            if let problem = collector.problem {
                finish(title: "Try Again", text: problem)
                return
            }

            state.lineUpPhase = .computing
            let points = collector.averagedPoints
            let moved = (collector.movedMillimeters, collector.movedDegrees, collector.expression)
            do {
                let lineUp = try await Task.detached(priority: .userInitiated) {
                    try LineUpMaker.make(points: points, head: head,
                                         movedMillimeters: moved.0, movedDegrees: moved.1,
                                         expression: moved.2)
                }.value
                guard lineUp.usedPoints >= 100 else {
                    finish(title: "Line-Up Failed",
                           text: "Only \(lineUp.usedPoints) mask points landed on the head's face. Is this the right head?")
                    return
                }
                var updated = head
                updated.lineUp = lineUp
                try heads.update(updated)
                finish(title: "Lined Up",
                       text: String(format: "Line-up error %.1f mm, using %d of %d mask points (%d rounds).",
                                    lineUp.rmsError * 1000, lineUp.usedPoints, lineUp.totalPoints,
                                    lineUp.iterations))
            } catch {
                finish(title: "Line-Up Failed", text: error.localizedDescription)
            }
        }
    }

    private func finish(title: String, text: String) {
        state.lineUpPhase = .idle
        message = (title, text)
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

        /// Expressions that change the face's shape; if any is strong, the face isn't relaxed.
        nonisolated private static let expressionKeys: [ARFaceAnchor.BlendShapeLocation] = [
            .jawOpen, .mouthSmileLeft, .mouthSmileRight, .mouthFunnel, .mouthPucker,
            .browInnerUp, .browOuterUpLeft, .browOuterUpRight, .browDownLeft, .browDownRight,
            .cheekPuff, .noseSneerLeft, .noseSneerRight,
        ]

        // Called on the main thread (the session's default delegate queue).
        nonisolated func session(_ session: ARSession, didUpdate frame: ARFrame) {
            // Apple's face pose in phone space: seen from the phone held upright.
            let face = frame.anchors.compactMap { $0 as? ARFaceAnchor }.first
            let tracked = face?.isTracked == true
            let transform = face.map { frame.camera.viewMatrix(for: .portrait) * $0.transform }
            let blendShapes = face?.blendShapes ?? [:]
            let expression = Self.expressionKeys.map { blendShapes[$0]?.floatValue ?? 0 }.max() ?? 0
            MainActor.assumeIsolated {
                if tracked, let transform {
                    state.status = .tracking
                    state.pose = HeadPose(transform: transform)
                    state.updateCount += 1
                    if let collector = state.collector, !collector.isDone, let face {
                        collector.add(vertices: face.geometry.vertices, pose: transform, expression: expression)
                        state.collectProgress = collector.progress
                    }
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
