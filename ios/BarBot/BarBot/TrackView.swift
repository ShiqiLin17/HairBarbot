//
//  TrackView.swift
//  BarBot
//
//  The Track tab: Apple's face tracking (ARKit) on the front 3D camera.
//  Shows the camera picture with Apple's face mask drawn on it, and the live
//  head pose relative to the phone. With a saved head chosen, "Line Up" snaps
//  Apple's mask onto that head's face (see LineUp.swift). After that, the whole
//  head is drawn on the picture and its pose is shown (option A: Apple's face
//  pose plus the fixed line-up offset).
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
import StandardCyborgFusion
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
    var showHead = true
    /// How solid the drawn head is (0 = invisible, 1 = solid).
    var headOpacity: Double = 0.3

    /// Live depth check (see DepthCheck.swift): on/off, the latest per-region numbers,
    /// and how many depth frames per second are being measured.
    var depthCheckOn = false
    var depthStats: [SCHeadRegion: RegionStats] = [:]
    var depthChecksPerSecond: Double = 0
    var depthLens = ""
    var depthMirrored = false
    var maskGap: (low: Float, median: Float, high: Float, count: Int)?
    /// Distance (meters) at which the dots reach full blue (inside) or full red (outside).
    var colorScale: Double = 0.01
    fileprivate var depthCount = 0
    fileprivate var depthCountStart = Date()

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
    /// The chosen head rebuilt as a mesh (for drawing it and comparing line-ups).
    @State private var mesh: HeadMesh?
    @AppStorage("trackPanelFolded") private var panelFolded = false

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
                FaceTrackingView(state: state,
                                 headMesh: head?.lineUp == nil ? nil : mesh,
                                 headKey: head.map { "\($0.name)|\($0.lineUp?.created.timeIntervalSince1970 ?? 0)" },
                                 headToFace: head?.lineUp?.headToFaceMatrix,
                                 headShape: head?.shapeData)
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
        .task(id: headName) {
            mesh = nil
            guard let head else { return }
            mesh = try? await Task.detached(priority: .userInitiated) { try HeadMesh.build(head) }.value
        }
        .alert(message?.title ?? "", isPresented: Binding(get: { message != nil },
                                                          set: { if !$0 { message = nil } })) {
            Button("OK") { message = nil }
        } message: {
            Text(message?.text ?? "")
        }
    }

    // MARK: Pieces

    /// The info panel at the top. Tap its top row to fold it down to one line.
    private var readout: some View {
        VStack(alignment: .leading, spacing: 3) {
            Button {
                withAnimation(.snappy) { panelFolded.toggle() }
            } label: {
                HStack(spacing: 6) {
                    Circle()
                        .fill(statusColor)
                        .frame(width: 9, height: 9)
                    Text(statusText).bold()
                    if panelFolded, let line = foldedLine {
                        Text(line).lineLimit(1)
                    }
                    Spacer()
                    Text(String(format: "%.0f /s", state.updatesPerSecond))
                        .foregroundStyle(.secondary)
                    Image(systemName: panelFolded ? "chevron.down" : "chevron.up")
                        .foregroundStyle(.secondary)
                }
                .contentShape(Rectangle())
            }
            .tint(.primary)

            if !panelFolded {
                if let pose = state.pose, state.status == .tracking {
                    let a = pose.angles
                    let p = pose.position * 100
                    Text(String(format: "face  turn %+5.1f°  nod %+5.1f°  tilt %+5.1f°  %.0f cm away",
                                a.turn, a.nod, a.tilt, -p.z))
                }
                if let lineUp = head?.lineUp {
                    if let headPose {
                        let a = headPose.angles
                        let p = headPose.position * 100
                        Text(String(format: "head  turn %+5.1f°  nod %+5.1f°  tilt %+5.1f°", a.turn, a.nod, a.tilt))
                        Text(String(format: "head center  x %+5.1f  y %+5.1f  z %+5.1f cm", p.x, p.y, p.z))
                            .foregroundStyle(.secondary)
                    }
                    Text(String(format: "line-up %.1f mm (%d pts)", lineUp.rmsError * 1000, lineUp.usedPoints)
                         + (lineUp.change.map { "  " + changeText($0) } ?? ""))
                        .foregroundStyle(.secondary)
                }
                if state.depthCheckOn {
                    Divider()
                    depthReadout
                }
            }
        }
        .font(.caption.monospacedDigit())
        .padding(10)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }

    /// The tracked head's pose in phone space (needs a line-up).
    private var headPose: HeadPose? {
        guard let lineUp = head?.lineUp, let pose = state.pose, state.status == .tracking else { return nil }
        return HeadPose(transform: pose.transform * lineUp.faceToHeadMatrix.inverse)
    }

    /// The one line shown when the panel is folded.
    private var foldedLine: String? {
        if state.depthCheckOn {
            let s = state.depthStats
            func mean(_ r: SCHeadRegion) -> String {
                guard let v = s[r], v.count >= 20 else { return "—" }
                return String(format: "%+.0f", v.mean * 1000)
            }
            return "face \(mean(.face)) ears \(mean(.leftEar))/\(mean(.rightEar)) mm"
        }
        if let a = (headPose ?? state.pose)?.angles {
            return String(format: "turn %+.0f° nod %+.0f° tilt %+.0f°", a.turn, a.nod, a.tilt)
        }
        return nil
    }

    /// Per-region depth errors: "rms (average)" in mm. Average + = points outside the head.
    private var depthReadout: some View {
        let s = state.depthStats
        func part(_ name: String, _ region: SCHeadRegion) -> String {
            guard let r = s[region], r.count >= 20 else { return "\(name) —" }
            return String(format: "%@ %.1f (%+.1f)", name, r.rms * 1000, r.mean * 1000)
        }
        return VStack(alignment: .leading, spacing: 2) {
            HStack {
                Text("depth check, mm: rms (average)").bold()
                Spacer()
                Text(String(format: "%.0f /s", state.depthChecksPerSecond)).foregroundStyle(.secondary)
            }
            Text(part("face", .face) + "   " + part("forehead", .forehead))
            Text(part("your left ear", .leftEar) + "   " + part("right ear", .rightEar))
            Text(part("scalp/hair", .scalp))
            HStack(spacing: 8) {
                legendDot(.blue, "inside")
                legendDot(.green, "on")
                legendDot(.red, "outside")
                Menu {
                    ForEach([2.0, 5.0, 10.0, 20.0], id: \.self) { mm in
                        Button(String(format: "full color at ±%.0f mm", mm)) { state.colorScale = mm / 1000 }
                    }
                } label: {
                    Text(String(format: "±%.0f mm ▾", state.colorScale * 1000))
                }
                Spacer()
            }
            if let gap = state.maskGap {
                Text(String(format: "Apple mask vs depth: %+.1f mm (middle half %+.1f to %+.1f, %d pts)",
                            gap.median * 1000, gap.low * 1000, gap.high * 1000, gap.count))
                    .bold()
                Text(gap.median > 0 ? "+ = Apple's mask floats in front of your real face"
                                    : "− = Apple's mask sits behind your real face")
                    .foregroundStyle(.secondary)
            } else {
                Text("Apple mask vs depth: —")
            }
            Text("\(state.depthLens) · flip \(state.depthMirrored ? "yes" : "no")")
                .foregroundStyle(.secondary)
        }
    }

    private func legendDot(_ color: Color, _ text: String) -> some View {
        HStack(spacing: 3) {
            Circle().fill(color).frame(width: 7, height: 7)
            Text(text)
        }
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
                Toggle("Head", isOn: $state.showHead)
                    .toggleStyle(.button)
                    .disabled(head?.lineUp == nil)
                Toggle("Depth", isOn: $state.depthCheckOn)
                    .toggleStyle(.button)
                    .disabled(head?.lineUp == nil)
            }

            if head?.lineUp != nil && state.showHead {
                HStack {
                    Image(systemName: "circle.dotted")
                    Slider(value: $state.headOpacity, in: 0.05...1)
                    Image(systemName: "circle.fill")
                }
                .foregroundStyle(.secondary)
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
                var newLineUp = lineUp
                if let previous = head.lineUp, let mesh {
                    newLineUp.change = LineUpChange.between(previous, lineUp, mesh: mesh)
                }
                var updated = head
                updated.lineUp = newLineUp
                try heads.update(updated)
                var text = String(format: "Line-up error %.1f mm, using %d of %d mask points (%d rounds).",
                                  lineUp.rmsError * 1000, lineUp.usedPoints, lineUp.totalPoints,
                                  lineUp.iterations)
                if let change = newLineUp.change { text += "\n\n" + changeText(change) }
                finish(title: "Lined Up", text: text)
            } catch {
                finish(title: "Line-Up Failed", text: error.localizedDescription)
            }
        }
    }

    private func changeText(_ change: LineUpChange) -> String {
        String(format: "vs previous: nose %.1f mm, back %.1f mm, top %.1f mm, %.1f°",
               change.noseMillimeters, change.backMillimeters, change.topMillimeters, change.degrees)
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
    /// The lined-up head to draw (nil = none), a key that changes when it or its line-up
    /// changes, and where it sits relative to Apple's face (head space → face space).
    let headMesh: HeadMesh?
    let headKey: String?
    let headToFace: simd_float4x4?
    /// The head's shape numbers, for the depth check.
    let headShape: Data?

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
        context.coordinator.setHead(mesh: headMesh, key: headKey, headToFace: headToFace,
                                    visible: state.showHead, opacity: state.headOpacity,
                                    shape: headShape)
        context.coordinator.pointsNode.isHidden = !state.depthCheckOn
    }

    static func dismantleUIView(_ view: ARSCNView, coordinator: Coordinator) {
        view.session.pause()
    }

    final class Coordinator: NSObject, ARSCNViewDelegate, ARSessionDelegate {
        let state: TrackState
        /// Read by SceneKit's drawing thread.
        nonisolated(unsafe) var maskVisible = true
        /// The node that follows Apple's face (made on SceneKit's thread), and the head drawn in it.
        nonisolated(unsafe) var faceNode: SCNNode?
        nonisolated(unsafe) var headNode: SCNNode?
        private var headKey: String?
        /// Depth points colored by distance, drawn in head space.
        nonisolated(unsafe) var pointsNode = SCNNode()
        private var checker: DepthChecker?
        private var headToFace: simd_float4x4?

        init(state: TrackState) { self.state = state }

        /// Puts the lined-up head inside the face node, so it moves with Apple's face pose.
        func setHead(mesh: HeadMesh?, key: String?, headToFace: simd_float4x4?, visible: Bool, opacity: Double,
                     shape: Data?) {
            self.headToFace = headToFace
            pointsNode.simdTransform = headToFace ?? matrix_identity_float4x4
            let wanted = mesh == nil ? nil : key
            if wanted != headKey {
                headKey = wanted
                headNode?.removeFromParentNode()
                headNode = nil
                checker = shape.flatMap { try? DepthChecker(shape: $0) }
                pointsNode.geometry = nil
                state.depthStats = [:]
                if let mesh {
                    let node = HeadFitSceneView.headNode(vertices: mesh.vertices, triangles: mesh.triangles,
                                                         transparency: 0.5)
                    node.renderingOrder = 10
                    headNode = node
                    faceNode?.addChildNode(node)
                }
            }
            if let headNode {
                headNode.simdTransform = headToFace ?? matrix_identity_float4x4
                headNode.isHidden = !visible || headToFace == nil
                headNode.geometry?.firstMaterial?.transparency = CGFloat(opacity)
            }
        }

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
                    if state.depthCheckOn, let face, let depth = frame.capturedDepthData,
                       let checker, let headToFace {
                        let input = DepthCheckInput(depth: depth,
                                                    intrinsics: frame.camera.intrinsics,
                                                    imageSize: frame.camera.imageResolution,
                                                    cameraToWorld: frame.camera.transform,
                                                    worldToHead: (face.transform * headToFace).inverse,
                                                    maskWorld: face.geometry.vertices.map { v in
                                                        let w = face.transform * SIMD4(v, 1)
                                                        return SIMD3(w.x, w.y, w.z)
                                                    })
                        checker.submit(input) { result in
                            Task { @MainActor in self.show(result) }
                        }
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

        /// Shows a measured depth frame: the numbers, and the points colored by signed distance
        /// from the head's surface (green = on it, blue = inside, red = outside).
        private func show(_ result: DepthCheckFrame) {
            guard state.depthCheckOn else { return }
            state.depthStats = result.stats
            state.depthLens = result.lens
            state.depthMirrored = result.mirrored
            state.maskGap = result.maskGap
            state.depthCount += 1
            let elapsed = Date().timeIntervalSince(state.depthCountStart)
            if elapsed >= 1 {
                state.depthChecksPerSecond = Double(state.depthCount) / elapsed
                state.depthCount = 0
                state.depthCountStart = Date()
            }

            var positions = [SCNVector3]()
            var colors = [SIMD4<Float>]()
            for i in result.points.indices where result.regions[i] != SCHeadRegion.none {
                let p = result.points[i]
                positions.append(SCNVector3(p.x, p.y, p.z))
                // Green on the surface, fading to blue (inside) or red (outside) at ±colorScale
                let t = max(-1, min(1, result.distances[i] / Float(state.colorScale)))
                let green = SIMD4<Float>(0.1, 0.85, 0.2, 1)
                let end: SIMD4<Float> = t < 0 ? SIMD4(0.15, 0.35, 1, 1) : SIMD4(1, 0.15, 0.1, 1)
                colors.append(green + (end - green) * abs(t))
            }
            guard !positions.isEmpty else { pointsNode.geometry = nil; return }
            let colorData = colors.withUnsafeBufferPointer { Data(buffer: $0) }
            let colorSource = SCNGeometrySource(data: colorData, semantic: .color, vectorCount: colors.count,
                                                usesFloatComponents: true, componentsPerVector: 4,
                                                bytesPerComponent: MemoryLayout<Float>.size,
                                                dataOffset: 0, dataStride: MemoryLayout<SIMD4<Float>>.stride)
            let element = SCNGeometryElement(indices: (0..<UInt32(positions.count)).map { $0 },
                                             primitiveType: .point)
            element.pointSize = 3
            element.minimumPointScreenSpaceRadius = 1.5
            element.maximumPointScreenSpaceRadius = 3
            let geometry = SCNGeometry(sources: [SCNGeometrySource(vertices: positions), colorSource],
                                       elements: [element])
            let material = SCNMaterial()
            material.lightingModel = .constant
            material.readsFromDepthBuffer = false   // always visible, even "inside" the drawn head
            geometry.materials = [material]
            pointsNode.geometry = geometry
            pointsNode.renderingOrder = 20
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
            let container = SCNNode()
            container.addChildNode(SCNNode(geometry: geometry))
            if let headNode { container.addChildNode(headNode) }
            container.addChildNode(pointsNode)
            faceNode = container
            return container
        }

        nonisolated func renderer(_ renderer: SCNSceneRenderer, didUpdate node: SCNNode, for anchor: ARAnchor) {
            guard let face = anchor as? ARFaceAnchor,
                  let maskNode = node.childNodes.first(where: { $0.geometry is ARSCNFaceGeometry }),
                  let geometry = maskNode.geometry as? ARSCNFaceGeometry else { return }
            geometry.update(from: face.geometry)
            maskNode.isHidden = !maskVisible
            // (Re)attach the head if it was made before this face node existed
            if let headNode, headNode.parent !== node { node.addChildNode(headNode) }
            if pointsNode.parent !== node { node.addChildNode(pointsNode) }
        }
    }
}
