//
//  HeadFitting.swift
//  Shared by BarBot (test app) and HairBarbot (user app)
//
//  Loading the FLAME head model, fitting it to a scan, and drawing a head mesh.
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

// MARK: - Drawing a head

enum HeadMeshNode {
    /// A head mesh with smooth shading in `color`. `transparency` 1 = solid.
    static func make(vertices: [Float], triangles: [UInt32], color: UIColor,
                     transparency: CGFloat = 1) -> SCNNode {
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
        material.diffuse.contents = color
        material.transparency = transparency
        material.isDoubleSided = true
        material.lightingModel = .blinn
        geometry.materials = [material]
        return SCNNode(geometry: geometry)
    }
}

/// A head mesh alone, front view, drag to rotate.
struct HeadMeshSceneView: UIViewRepresentable {
    let mesh: HeadMesh
    /// Skin color of the head (BarBot: skin tone; HairBarbot: brand warm white).
    var color: UIColor = UIColor(red: 0.93, green: 0.76, blue: 0.66, alpha: 1)
    var background: UIColor = .systemBackground

    func makeUIView(context: Context) -> SCNView {
        let view = SCNView()
        let scene = SCNScene()
        var center = SIMD3<Float>(0, 0, 0)
        for i in stride(from: 0, to: mesh.vertices.count, by: 3) {
            center += SIMD3(mesh.vertices[i], mesh.vertices[i + 1], mesh.vertices[i + 2])
        }
        center /= Float(max(1, mesh.vertices.count / 3))
        let node = HeadMeshNode.make(vertices: mesh.vertices, triangles: mesh.triangles, color: color)
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
        view.backgroundColor = background
        return view
    }

    func updateUIView(_ view: SCNView, context: Context) {}
}
