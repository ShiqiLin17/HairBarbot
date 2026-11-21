//
//  LineUp.swift
//  BarBot
//
//  The line-up (calibration) between Apple's face mask and a saved head.
//
//  1. Collect: for about a second, add up Apple's 1220 mask points (in Apple's
//     face space, so small head motions don't matter) and average them.
//     Also check that the head stayed still and the face stayed relaxed.
//  2. Snap the averaged mask onto the head's face (SCFaceLineUp in the fork).
//  3. Save the result in the head's file: the fixed offset from Apple's face
//     space to head space, the line-up error, and where each mask point landed.
//
//  Live, the head's pose in phone space is then:
//     phone ← head  =  (phone ← Apple face, from ARKit)  ×  (Apple face ← head)
//

import Foundation
import simd
import StandardCyborgFusion

/// A finished line-up, stored in the head's JSON file.
nonisolated struct LineUp: Codable, Hashable, Sendable {
    var created: Date
    /// 4×4 transform from Apple's face space to head space, 16 numbers column by column.
    var faceToHead: [Float]
    /// Distance left between the mask and the head's face (meters, root-mean-square).
    var rmsError: Float
    var usedPoints: Int
    var totalPoints: Int
    var iterations: Int
    /// How much the head moved and how expressive the face was while collecting.
    var movedMillimeters: Float
    var movedDegrees: Float
    var expression: Float
    /// For each mask point: its spot on the head (x, y, z; head space) and whether it was used.
    var matchedHeadPoints: [Float]
    var matchedFlags: [UInt8]
    /// How much the head moved compared with the line-up before this one (nil for the first).
    var change: LineUpChange?

    var faceToHeadMatrix: simd_float4x4 {
        guard faceToHead.count == 16 else { return matrix_identity_float4x4 }
        let f = faceToHead
        return simd_float4x4(columns: (SIMD4(f[0], f[1], f[2], f[3]),
                                       SIMD4(f[4], f[5], f[6], f[7]),
                                       SIMD4(f[8], f[9], f[10], f[11]),
                                       SIMD4(f[12], f[13], f[14], f[15])))
    }

    /// Head space → Apple face space.
    var headToFaceMatrix: simd_float4x4 { faceToHeadMatrix.inverse }
}

/// How far apart two line-ups put the same head: millimeters at the nose tip, the back of
/// the head and the top of the head, and the turn between them in degrees.
nonisolated struct LineUpChange: Codable, Hashable, Sendable {
    var noseMillimeters: Float
    var backMillimeters: Float
    var topMillimeters: Float
    var degrees: Float

    /// Compares where two line-ups place the head's nose tip, back and top (relative to Apple's face).
    static func between(_ old: LineUp, _ new: LineUp, mesh: HeadMesh) -> LineUpChange {
        var nose = SIMD3<Float>(0, 0, -.greatestFiniteMagnitude)
        var back = SIMD3<Float>(0, 0, .greatestFiniteMagnitude)
        var top = SIMD3<Float>(0, -.greatestFiniteMagnitude, 0)
        for i in stride(from: 0, to: mesh.vertices.count, by: 3) {
            let p = SIMD3(mesh.vertices[i], mesh.vertices[i + 1], mesh.vertices[i + 2])
            if p.z > nose.z { nose = p }
            if p.z < back.z { back = p }
            if p.y > top.y { top = p }
        }
        let a = old.headToFaceMatrix, b = new.headToFaceMatrix
        func moved(_ p: SIMD3<Float>) -> Float {
            let pa = a * SIMD4(p, 1), pb = b * SIMD4(p, 1)
            return simd_length(SIMD3(pa.x - pb.x, pa.y - pb.y, pa.z - pb.z)) * 1000
        }
        let relative = old.faceToHeadMatrix * b
        let trace = relative.columns.0.x + relative.columns.1.y + relative.columns.2.z
        let degrees = acos(max(-1, min(1, (trace - 1) / 2))) * 180 / .pi
        return LineUpChange(noseMillimeters: moved(nose), backMillimeters: moved(back),
                            topMillimeters: moved(top), degrees: degrees)
    }
}

/// Adds up mask frames while the line-up is collecting.
final class LineUpCollector {
    static let framesNeeded = 60          // about 1 second
    static let maxMovedMillimeters: Float = 10
    static let maxMovedDegrees: Float = 3
    static let maxExpression: Float = 0.35

    private(set) var frames = 0
    private var sums: [SIMD3<Double>] = []
    private var firstPose: simd_float4x4?
    private(set) var movedMillimeters: Float = 0
    private(set) var movedDegrees: Float = 0
    private var expressionSum: Float = 0

    var progress: Double { Double(frames) / Double(Self.framesNeeded) }
    var isDone: Bool { frames >= Self.framesNeeded }
    var expression: Float { frames > 0 ? expressionSum / Float(frames) : 0 }

    /// One frame: the mask points (face space), Apple's face pose (phone space),
    /// and the strongest expression value (0 = relaxed, 1 = full smile/open mouth/…).
    func add(vertices: [SIMD3<Float>], pose: simd_float4x4, expression: Float) {
        if sums.isEmpty { sums = Array(repeating: .zero, count: vertices.count) }
        guard vertices.count == sums.count else { return }
        for i in vertices.indices { sums[i] += SIMD3<Double>(vertices[i]) }
        if let firstPose {
            let shift = simd_length(pose.columns.3 - firstPose.columns.3) * 1000
            let relative = simd_mul(rotation(firstPose).transpose, rotation(pose))
            let cosine = max(-1, min(1, (relative.columns.0.x + relative.columns.1.y + relative.columns.2.z - 1) / 2))
            movedMillimeters = max(movedMillimeters, shift)
            movedDegrees = max(movedDegrees, acos(cosine) * 180 / .pi)
        } else {
            firstPose = pose
        }
        expressionSum += expression
        frames += 1
    }

    /// Averaged mask points, as float32 x, y, z.
    var averagedPoints: Data {
        let n = Double(max(1, frames))
        var floats = [Float]()
        floats.reserveCapacity(sums.count * 3)
        for s in sums { floats += [Float(s.x / n), Float(s.y / n), Float(s.z / n)] }
        return floats.withUnsafeBufferPointer { Data(buffer: $0) }
    }

    /// Why this collection can't be used, if it can't.
    var problem: String? {
        if movedMillimeters > Self.maxMovedMillimeters || movedDegrees > Self.maxMovedDegrees {
            return String(format: "Your head moved %.0f mm / %.1f° while lining up. Hold still and try again.",
                          movedMillimeters, movedDegrees)
        }
        if expression > Self.maxExpression {
            return "Your face wasn't relaxed (smiling, mouth open or eyebrows up). Relax your face and try again."
        }
        return nil
    }

    private func rotation(_ m: simd_float4x4) -> simd_float3x3 {
        simd_float3x3(columns: (SIMD3(m.columns.0.x, m.columns.0.y, m.columns.0.z),
                                SIMD3(m.columns.1.x, m.columns.1.y, m.columns.1.z),
                                SIMD3(m.columns.2.x, m.columns.2.y, m.columns.2.z)))
    }
}

enum LineUpMaker {
    /// Snaps the averaged mask onto the head. Takes a fraction of a second; call off the main thread.
    nonisolated static func make(points: Data, head: SavedHead,
                                 movedMillimeters: Float, movedDegrees: Float,
                                 expression: Float) throws -> LineUp {
        let model = try HeadModelLoader.shared.get()
        let result = SCFaceLineUp.lineUp(facePoints: points, head: model, shape: head.shapeData)
        let m = result.faceToHead
        let columns = [m.columns.0, m.columns.1, m.columns.2, m.columns.3]
        return LineUp(created: Date(),
                      faceToHead: columns.flatMap { [$0.x, $0.y, $0.z, $0.w] },
                      rmsError: result.rmsError,
                      usedPoints: result.usedPointCount,
                      totalPoints: points.count / (3 * MemoryLayout<Float>.size),
                      iterations: result.iterations,
                      movedMillimeters: movedMillimeters,
                      movedDegrees: movedDegrees,
                      expression: expression,
                      matchedHeadPoints: result.matchedHeadPoints.floats,
                      matchedFlags: [UInt8](result.matchedFlags))
    }
}
