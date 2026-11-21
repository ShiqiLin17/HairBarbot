//
//  HeadStore.swift
//  BarBot
//
//  Saved heads for tracking. A head is just the fitted FLAME shape numbers
//  (100 numbers) plus a few facts about the fit, stored as a small JSON file in
//  Documents/Heads. The full head is rebuilt from the numbers when needed, in the
//  model's own clean "head space" (meters, y = up, z = out of the face), not
//  tilted the way the scan happened to be.
//

import Foundation
import Observation
import StandardCyborgFusion

/// One saved head (the contents of a Heads/<name>.json file).
nonisolated struct SavedHead: Codable, Identifiable, Hashable, Sendable {
    /// File format version, in case it changes later.
    var version = 1
    /// Which head model the shape numbers belong to.
    var model = "FLAME 2023 Open"
    var name: String
    /// The scan the head was fitted to.
    var sourceScan: String
    var created: Date
    /// FLAME shape coefficients (~0 = average head, ±2 = unusual).
    var shape: [Float]

    /// Fit quality when it was saved (meters; nil if there were no points in that region).
    var fitRms: Float?
    var faceRms: Float?
    var scalpRms: Float?
    var coverage: Float?

    /// The latest line-up with Apple's face mask (nil until you do one in the Track tab).
    var lineUp: LineUp?

    var id: String { name }

    var shapeData: Data { shape.withUnsafeBufferPointer { Data(buffer: $0) } }
}

enum HeadStoreError: LocalizedError {
    case emptyName
    case writeFailed(String)

    var errorDescription: String? {
        switch self {
        case .emptyName: "Please enter a name."
        case .writeFailed(let reason): "The head could not be saved: \(reason)"
        }
    }
}

@Observable
final class HeadStore {
    /// Saved heads, newest first.
    private(set) var heads: [SavedHead] = []

    /// Documents/Heads (also holds exported OBJ files; those are ignored here).
    let folder: URL = URL.documentsDirectory.appending(path: "Heads", directoryHint: .isDirectory)

    init() {
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        reload()
    }

    func reload() {
        let urls = (try? FileManager.default.contentsOfDirectory(at: folder, includingPropertiesForKeys: nil)) ?? []
        heads = urls
            .filter { $0.pathExtension.lowercased() == "json" }
            .compactMap { url in
                guard let data = try? Data(contentsOf: url) else { return nil }
                return try? Self.decoder.decode(SavedHead.self, from: data)
            }
            .sorted { $0.created > $1.created }
    }

    func exists(named name: String) -> Bool {
        FileManager.default.fileExists(atPath: url(for: ScanStore.cleanName(name)).path)
    }

    /// Saves the fitted shape under `name`. Replaces a head with the same name.
    @discardableResult
    func save(_ result: SCHeadFitResult, from scan: SavedScan, named name: String) throws -> SavedHead {
        let cleaned = ScanStore.cleanName(name)
        guard !cleaned.isEmpty else { throw HeadStoreError.emptyName }
        let shape = result.shapeCoefficients.withUnsafeBytes { Array($0.bindMemory(to: Float.self)) }
        func finite(_ value: Float) -> Float? { value.isFinite ? value : nil }
        let head = SavedHead(name: cleaned,
                             sourceScan: scan.name,
                             created: Date(),
                             shape: shape,
                             fitRms: finite(result.rmsError),
                             faceRms: finite(result.faceRmsError),
                             scalpRms: finite(result.scalpRmsError),
                             coverage: finite(result.coverage))
        do {
            let data = try Self.encoder.encode(head)
            try data.write(to: url(for: cleaned), options: .atomic)
        } catch {
            throw HeadStoreError.writeFailed(error.localizedDescription)
        }
        reload()
        return head
    }

    /// Writes a changed head (e.g. with a new line-up) back to its file.
    func update(_ head: SavedHead) throws {
        do {
            let data = try Self.encoder.encode(head)
            try data.write(to: url(for: head.name), options: .atomic)
        } catch {
            throw HeadStoreError.writeFailed(error.localizedDescription)
        }
        reload()
    }

    func delete(_ head: SavedHead) {
        try? FileManager.default.removeItem(at: url(for: head.name))
        reload()
    }

    private func url(for name: String) -> URL {
        folder.appending(path: "\(name).json")
    }

    private static let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }()

    private static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }()
}

/// A saved head rebuilt as a mesh, in head space.
struct HeadMesh: @unchecked Sendable {
    let vertices: [Float]     // vertexCount × 3
    let triangles: [UInt32]   // triangleCount × 3

    nonisolated static func build(_ head: SavedHead) throws -> HeadMesh {
        let model = try HeadModelLoader.shared.get()
        return HeadMesh(vertices: model.vertices(forShape: head.shapeData).floats,
                        triangles: model.triangles.uint32s)
    }

    /// Size of the whole mesh along each axis (meters): x = ear to ear, y = up, z = front to back.
    var size: SIMD3<Float> {
        var low = SIMD3<Float>(repeating: .greatestFiniteMagnitude)
        var high = -low
        for i in stride(from: 0, to: vertices.count, by: 3) {
            let p = SIMD3(vertices[i], vertices[i + 1], vertices[i + 2])
            low = simd_min(low, p)
            high = simd_max(high, p)
        }
        return high - low
    }
}

extension Data {
    nonisolated var floats: [Float] { withUnsafeBytes { Array($0.bindMemory(to: Float.self)) } }
    nonisolated var uint32s: [UInt32] { withUnsafeBytes { Array($0.bindMemory(to: UInt32.self)) } }
}
