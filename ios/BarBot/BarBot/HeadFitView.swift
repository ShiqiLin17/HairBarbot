//
//  HeadFitView.swift
//  BarBot
//
//  Fitting the FLAME head model to a saved scan, and showing the result:
//  the fitted head (see-through) with the scan's points colored by how far
//  they are from it (green < 2 mm, yellow < 5 mm, red farther).
//
//  "Test with another scan" keeps the fitted head's shape and only moves it
//  onto a different scan, to check how well it predicts parts the first scan
//  didn't see (e.g. fit to a front scan, test against a back scan).
//
//  FLAME 2023 Open: Li, Bolkart, Black, Li, Romero, "Learning a model of facial
//  shape and expression from 4D scans", SIGGRAPH Asia 2017. CC-BY-4.0.
//

import SceneKit
import SwiftUI
import StandardCyborgFusion

// MARK: - Loading the model

enum HeadModelLoader {
    /// Loaded once, on first use (FLAMEHead.bin + FLAMEMasks.bin from the app bundle).
    nonisolated(unsafe) static let shared: Result<SCHeadModel, Error> = {
        guard let modelPath = Bundle.main.path(forResource: "FLAMEHead", ofType: "bin"),
              let masksPath = Bundle.main.path(forResource: "FLAMEMasks", ofType: "bin") else {
            return .failure(LoadError.missingFiles)
        }
        do {
            return .success(try SCHeadModel(modelPath: modelPath, masksPath: masksPath))
        } catch {
            return .failure(error)
        }
    }()

    enum LoadError: LocalizedError {
        case missingFiles
        var errorDescription: String? {
            "The head model files are missing from the app. Run tools/flame/convert_flame.py, then rebuild."
        }
    }
}

/// A finished fit, carried between threads.
struct HeadFit: @unchecked Sendable {
    let scan: SavedScan
    let result: SCHeadFitResult
    let seconds: Double
    /// The turn the scan's label suggested (nil if it had no front/left/right/back label).
    let expectedYaw: Float?
}

enum HeadFitter {
    /// Fits the model to a scan. With `shape`, keeps that shape and only places it.
    nonisolated static func fit(_ scan: SavedScan, keepingShapeOf shape: Data? = nil) throws -> HeadFit {
        let model = try HeadModelLoader.shared.get()
        guard let pointCloud = SCPointCloud(plyPath: scan.url.path) else {
            throw CocoaError(.fileReadCorruptFile, userInfo: [NSLocalizedDescriptionKey: "Couldn't open \(scan.name)."])
        }
        let expected = scan.side.flatMap { model.expectedYawDegrees(forLabel: $0) }
        let start = Date()
        let result = SCHeadModelFitting.fit(model, to: pointCloud,
                                            expectedYawDegrees: expected,
                                            fixedShape: shape)
        return HeadFit(scan: scan, result: result,
                       seconds: Date().timeIntervalSince(start), expectedYaw: expected?.floatValue)
    }
}

// MARK: - Screen

struct HeadFitScreen: View {
    let scan: SavedScan
    let store: ScanStore
    let onClose: () -> Void

    @State private var fit: HeadFit?
    @State private var test: HeadFit?
    @State private var showingTest = false
    @State private var status: String? = "Fitting head model…"
    @State private var errorMessage: String?
    @State private var choosingTestScan = false
    @State private var showHead = true
    @State private var showPoints = true
    @State private var savedMessage: String?
    @State private var namingForTracking = false
    @State private var trackingName = ""
    @Environment(HeadStore.self) private var heads

    /// What's on screen: the fit itself, or the test against another scan.
    private var shown: HeadFit? { showingTest ? test : fit }

    var body: some View {
        NavigationStack {
            ZStack {
                Color(.systemBackground).ignoresSafeArea()
                if let shown {
                    HeadFitSceneView(fit: shown, showHead: showHead, showPoints: showPoints)
                        .ignoresSafeArea(edges: .bottom)
                        .id("\(shown.scan.id)-\(showHead)-\(showPoints)")
                }
                VStack {
                    if let shown { report(for: shown).padding(.horizontal) }
                    Spacer()
                    if let status { progress(status) }
                    if let errorMessage {
                        Text(errorMessage).foregroundStyle(.red).padding()
                    }
                    Spacer()
                    if fit != nil { controls }
                }
            }
            .navigationTitle(scan.name)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close", action: onClose)
                }
                ToolbarItem(placement: .primaryAction) {
                    Menu("Save") {
                        Button {
                            trackingName = scan.name
                            namingForTracking = true
                        } label: {
                            Label("Use for Tracking…", systemImage: "face.dashed")
                        }
                        Button(action: saveHead) {
                            Label("Export OBJ", systemImage: "square.and.arrow.down")
                        }
                    }
                    .disabled(fit == nil)
                }
            }
            .alert("Save Head for Tracking", isPresented: $namingForTracking) {
                TextField("Name", text: $trackingName)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)
                Button("Save") { saveForTracking() }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("Saves this head's shape (not the scan's tilt). A head with the same name is replaced.")
            }
            .sheet(isPresented: $choosingTestScan) {
                TestScanPicker(store: store, excluding: scan) { picked in
                    choosingTestScan = false
                    runTest(against: picked)
                }
            }
            .alert("Saved", isPresented: Binding(get: { savedMessage != nil },
                                                 set: { if !$0 { savedMessage = nil } })) {
                Button("OK") { savedMessage = nil }
            } message: {
                Text(savedMessage ?? "")
            }
        }
        .task { await runFit() }
    }

    // MARK: Pieces

    private func progress(_ text: String) -> some View {
        VStack(spacing: 12) {
            ProgressView()
            Text(text)
        }
        .padding(24)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
    }

    private func report(for fit: HeadFit) -> some View {
        let r = fit.result
        return VStack(alignment: .leading, spacing: 3) {
            if showingTest {
                Text("Test: \(fit.scan.name) against the fitted head").bold()
            }
            Text(String(format: "fit  rms %@   median %@   90%% %@",
                        mm(r.rmsError), mm(r.medianError), mm(r.p90Error)))
            Text(String(format: "scalp %@   face %@   coverage %.0f%%",
                        mm(r.scalpRmsError), mm(r.faceRmsError), r.coverage * 100))
            Text(turnLine(fit) + String(format: "   neck cut %@   %.1f s",
                                        r.bodyCutDepth > 0 ? String(format: "%.0f cm", r.bodyCutDepth * 100) : "none",
                                        fit.seconds))
                .foregroundStyle(.secondary)
            legend
        }
        .font(.caption.monospacedDigit())
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 10))
    }

    private var legend: some View {
        HStack(spacing: 10) {
            legendDot(.green, "< 2 mm")
            legendDot(.yellow, "< 5 mm")
            legendDot(.red, "farther")
        }
    }

    private func legendDot(_ color: Color, _ text: String) -> some View {
        HStack(spacing: 4) {
            Circle().fill(color).frame(width: 8, height: 8)
            Text(text)
        }
    }

    private func turnLine(_ fit: HeadFit) -> String {
        var text = String(format: "turn %.0f°", fit.result.yawDegrees)
        if let expected = fit.expectedYaw {
            text += String(format: " (label %@: %.0f°)", fit.scan.side ?? "", expected)
        }
        return text
    }

    private var controls: some View {
        VStack(spacing: 10) {
            HStack {
                Toggle("Head", isOn: $showHead)
                Toggle("Points", isOn: $showPoints)
            }
            .toggleStyle(.button)

            if test != nil {
                Picker("Showing", selection: $showingTest) {
                    Text("Fit").tag(false)
                    Text("Test").tag(true)
                }
                .pickerStyle(.segmented)
            }

            Button {
                choosingTestScan = true
            } label: {
                Label("Test with another scan…", systemImage: "checkmark.circle")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(status != nil)
        }
        .padding()
        .background(.ultraThinMaterial)
    }

    private func mm(_ meters: Float) -> String {
        meters.isFinite ? String(format: "%.1f mm", meters * 1000) : "—"
    }

    // MARK: Actions

    private func runFit() async {
        let scan = scan
        do {
            fit = try await Task.detached(priority: .userInitiated) {
                try HeadFitter.fit(scan)
            }.value
            status = nil
        } catch {
            status = nil
            errorMessage = error.localizedDescription
        }
    }

    private func runTest(against other: SavedScan) {
        guard let shape = fit?.result.shapeCoefficients else { return }
        status = "Testing against \(other.name)…"
        Task {
            do {
                test = try await Task.detached(priority: .userInitiated) {
                    try HeadFitter.fit(other, keepingShapeOf: shape)
                }.value
                showingTest = true
            } catch {
                errorMessage = error.localizedDescription
            }
            status = nil
        }
    }

    /// Saves the fitted shape (not the test's) as a head for tracking.
    private func saveForTracking() {
        guard let fit else { return }
        do {
            let replaced = heads.exists(named: trackingName)
            let head = try heads.save(fit.result, from: scan, named: trackingName)
            savedMessage = "Saved head \"\(head.name)\"" + (replaced ? " (replaced the old one)." : ".")
                + " It's listed under Saved heads in the Scan tab."
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Writes the fitted head as an OBJ mesh to Documents/Heads (visible in the Files app).
    private func saveHead() {
        guard let fit else { return }
        let folder = URL.documentsDirectory.appending(path: "Heads", directoryHint: .isDirectory)
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let url = folder.appending(path: "\(scan.name)-head.obj")

        let vertices = fit.result.vertices.floats
        let triangles = fit.result.triangles.uint32s
        var obj = "# FLAME 2023 Open head fitted to \(scan.name) (FLAME: CC-BY-4.0, Li et al. 2017)\n"
        obj.reserveCapacity(vertices.count * 12 + triangles.count * 8)
        for i in stride(from: 0, to: vertices.count, by: 3) {
            obj += String(format: "v %.5f %.5f %.5f\n", vertices[i], vertices[i + 1], vertices[i + 2])
        }
        for i in stride(from: 0, to: triangles.count, by: 3) {
            obj += "f \(triangles[i] + 1) \(triangles[i + 1] + 1) \(triangles[i + 2] + 1)\n"
        }
        do {
            try obj.write(to: url, atomically: true, encoding: .utf8)
            savedMessage = "Saved \(url.lastPathComponent) to Files → On My iPhone → BarBot → Heads."
        } catch {
            errorMessage = "Couldn't save: \(error.localizedDescription)"
        }
    }
}

/// Picks the scan to test the fitted head against.
private struct TestScanPicker: View {
    let store: ScanStore
    let excluding: SavedScan
    let onPick: (SavedScan) -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List(store.scans.filter { $0 != excluding }) { scan in
                Button(scan.name) { onPick(scan) }
                    .tint(.primary)
            }
            .navigationTitle("Test against…")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
    }
}

// MARK: - 3D view

/// The fitted head (see-through skin color) and the scan's points colored by distance.
struct HeadFitSceneView: UIViewRepresentable {
    let fit: HeadFit
    let showHead: Bool
    let showPoints: Bool

    func makeUIView(context: Context) -> SCNView {
        let view = SCNView()
        view.scene = makeScene()
        view.allowsCameraControl = true
        view.autoenablesDefaultLighting = true
        view.backgroundColor = .systemBackground
        return view
    }

    func updateUIView(_ view: SCNView, context: Context) {}

    private func makeScene() -> SCNScene {
        let scene = SCNScene()
        let vertices = fit.result.vertices.floats
        let triangles = fit.result.triangles.uint32s

        // Center everything on the head, so the camera orbits around it
        var center = SIMD3<Float>(0, 0, 0)
        for i in stride(from: 0, to: vertices.count, by: 3) {
            center += SIMD3(vertices[i], vertices[i + 1], vertices[i + 2])
        }
        center /= Float(max(1, vertices.count / 3))
        let root = SCNNode()
        root.simdPosition = -center
        scene.rootNode.addChildNode(root)

        if showHead { root.addChildNode(Self.headNode(vertices: vertices, triangles: triangles)) }
        if showPoints { root.addChildNode(pointsNode()) }

        // Camera in front of the scan (scans look along -z from the camera at the origin)
        let camera = SCNNode()
        camera.camera = SCNCamera()
        camera.camera?.zNear = 0.01
        camera.simdPosition = SIMD3<Float>(0, 0.02, 0.45)
        camera.simdLook(at: .zero)
        scene.rootNode.addChildNode(camera)
        return scene
    }

    /// A head mesh in skin color with smooth shading. `transparency` 1 = solid.
    static func headNode(vertices: [Float], triangles: [UInt32], transparency: CGFloat = 0.55) -> SCNNode {
        let count = vertices.count / 3
        var positions = [SCNVector3]()
        positions.reserveCapacity(count)
        for i in 0..<count {
            positions.append(SCNVector3(vertices[3 * i], vertices[3 * i + 1], vertices[3 * i + 2]))
        }
        // Smooth normals from the triangles
        var normals = [SIMD3<Float>](repeating: .zero, count: count)
        for f in stride(from: 0, to: triangles.count, by: 3) {
            let a = Int(triangles[f]), b = Int(triangles[f + 1]), c = Int(triangles[f + 2])
            let pa = SIMD3(vertices[3 * a], vertices[3 * a + 1], vertices[3 * a + 2])
            let pb = SIMD3(vertices[3 * b], vertices[3 * b + 1], vertices[3 * b + 2])
            let pc = SIMD3(vertices[3 * c], vertices[3 * c + 1], vertices[3 * c + 2])
            let n = simd_cross(pb - pa, pc - pa)
            normals[a] += n; normals[b] += n; normals[c] += n
        }
        let normalVectors = normals.map { n -> SCNVector3 in
            let u = simd_length(n) > 0 ? simd_normalize(n) : SIMD3(0, 0, 1)
            return SCNVector3(u.x, u.y, u.z)
        }

        let geometry = SCNGeometry(sources: [SCNGeometrySource(vertices: positions),
                                             SCNGeometrySource(normals: normalVectors)],
                                   elements: [SCNGeometryElement(indices: triangles, primitiveType: .triangles)])
        let material = SCNMaterial()
        material.diffuse.contents = UIColor(red: 0.93, green: 0.76, blue: 0.66, alpha: 1)
        material.transparency = transparency
        material.isDoubleSided = true
        material.lightingModel = .blinn
        geometry.materials = [material]
        return SCNNode(geometry: geometry)
    }

    private func pointsNode() -> SCNNode {
        let points = fit.result.scanPoints.floats
        let distances = fit.result.scanDistances.floats
        let count = min(points.count / 3, distances.count)
        var positions = [SCNVector3]()
        var colors = [SIMD4<Float>]()
        positions.reserveCapacity(count)
        colors.reserveCapacity(count)
        for i in 0..<count {
            positions.append(SCNVector3(points[3 * i], points[3 * i + 1], points[3 * i + 2]))
            let d = abs(distances[i])
            let color: SIMD4<Float> = !d.isFinite ? SIMD4(0.6, 0.6, 0.6, 1)
                : d < 0.002 ? SIMD4(0.1, 0.8, 0.2, 1)
                : d < 0.005 ? SIMD4(0.95, 0.8, 0.1, 1)
                : SIMD4(0.9, 0.15, 0.1, 1)
            colors.append(color)
        }
        let colorData = colors.withUnsafeBufferPointer { Data(buffer: $0) }
        let colorSource = SCNGeometrySource(data: colorData, semantic: .color, vectorCount: count,
                                            usesFloatComponents: true, componentsPerVector: 4,
                                            bytesPerComponent: MemoryLayout<Float>.size,
                                            dataOffset: 0, dataStride: MemoryLayout<SIMD4<Float>>.stride)
        let indices = (0..<UInt32(count)).map { $0 }
        let element = SCNGeometryElement(indices: indices, primitiveType: .point)
        element.pointSize = 3
        element.minimumPointScreenSpaceRadius = 1.5
        element.maximumPointScreenSpaceRadius = 4
        let geometry = SCNGeometry(sources: [SCNGeometrySource(vertices: positions), colorSource], elements: [element])
        let material = SCNMaterial()
        material.lightingModel = .constant
        geometry.materials = [material]
        return SCNNode(geometry: geometry)
    }
}

// MARK: - Saved head viewer

/// Shows a saved head, rebuilt from its shape numbers, in head space (facing you).
struct SavedHeadScreen: View {
    let head: SavedHead
    let onClose: () -> Void

    @State private var mesh: HeadMesh?
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            ZStack {
                Color(.systemBackground).ignoresSafeArea()
                if let mesh {
                    HeadMeshSceneView(mesh: mesh)
                        .ignoresSafeArea(edges: .bottom)
                }
                VStack {
                    info.padding(.horizontal)
                    Spacer()
                    if let errorMessage {
                        Text(errorMessage).foregroundStyle(.red).padding()
                    }
                    Spacer()
                }
            }
            .navigationTitle(head.name)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close", action: onClose)
                }
            }
        }
        .task {
            let head = head
            do {
                mesh = try await Task.detached(priority: .userInitiated) { try HeadMesh.build(head) }.value
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    private var info: some View {
        VStack(alignment: .leading, spacing: 3) {
            Text("from \(head.sourceScan)")
            Text("saved \(head.created.formatted(date: .abbreviated, time: .shortened))")
            Text("fit  rms \(mm(head.fitRms))   face \(mm(head.faceRms))   scalp \(mm(head.scalpRms))")
            if let mesh {
                let size = mesh.size * 100
                Text(String(format: "model size  width %.1f cm   height %.1f cm   depth %.1f cm",
                            size.x, size.y, size.z))
            }
            Text(String(format: "shape: %d numbers, how unusual %.2f (0 = average head)",
                        head.shape.count, unusualness))
                .foregroundStyle(.secondary)
        }
        .font(.caption.monospacedDigit())
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 10))
    }

    /// Root-mean-square of the shape numbers: ~0 for an average head, ~1 for a typical person.
    private var unusualness: Float {
        guard !head.shape.isEmpty else { return 0 }
        return (head.shape.reduce(0) { $0 + $1 * $1 } / Float(head.shape.count)).squareRoot()
    }

    private func mm(_ meters: Float?) -> String {
        guard let meters, meters.isFinite else { return "—" }
        return String(format: "%.1f mm", meters * 1000)
    }
}

/// A head mesh alone, front view, drag to rotate.
struct HeadMeshSceneView: UIViewRepresentable {
    let mesh: HeadMesh

    func makeUIView(context: Context) -> SCNView {
        let view = SCNView()
        let scene = SCNScene()
        var center = SIMD3<Float>(0, 0, 0)
        for i in stride(from: 0, to: mesh.vertices.count, by: 3) {
            center += SIMD3(mesh.vertices[i], mesh.vertices[i + 1], mesh.vertices[i + 2])
        }
        center /= Float(max(1, mesh.vertices.count / 3))
        let node = HeadFitSceneView.headNode(vertices: mesh.vertices, triangles: mesh.triangles, transparency: 1)
        node.simdPosition = -center
        scene.rootNode.addChildNode(node)

        let camera = SCNNode()
        camera.camera = SCNCamera()
        camera.camera?.zNear = 0.01
        camera.simdPosition = SIMD3<Float>(0, 0.02, 0.45)
        camera.simdLook(at: .zero)
        scene.rootNode.addChildNode(camera)

        view.scene = scene
        view.allowsCameraControl = true
        view.autoenablesDefaultLighting = true
        view.backgroundColor = .systemBackground
        return view
    }

    func updateUIView(_ view: SCNView, context: Context) {}
}
