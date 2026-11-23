//
//  DepthCheck.swift
//  BarBot
//
//  Live depth check: during face tracking, ARKit also delivers the front 3D
//  camera's real depth picture (about 15 times per second). This turns that
//  picture into 3D points, moves them into head space using the current tracked
//  head pose, and measures how far each one is from the head's surface.
//
//  If the tracked head is in the right place, depth points on your face, ears
//  and forehead sit on the head's surface (green). If the head is shifted or
//  turned, one side shows up consistently outside (+) and the other inside (-).
//  Hair sticks out past the head; points more than 2 cm away aren't counted.
//
//  Depth correction ("Fix"): before measuring, the depth points on the firm, hair-free
//  parts of the head (face without lips and eyes, nose, ears) are snapped onto the head
//  model. The small move that takes is the error in Apple's face pose right now; the
//  Track tab applies it to Apple's pose until the next depth picture. The forehead and
//  scalp aren't used for the snap, so their numbers are an independent check.
//

import AVFoundation
import os
import simd
import StandardCyborgFusion

/// Error numbers for one head region (meters).
nonisolated struct RegionStats: Sendable {
    /// Root-mean-square distance: how far off, on average.
    var rms: Float
    /// Average signed distance: + = points outside the head (head too small or shifted away),
    /// - = points inside the head.
    var mean: Float
    var count: Int
}

/// One measured depth frame.
nonisolated struct DepthCheckFrame: @unchecked Sendable {
    /// Measured points near the head (head space), their signed distances, and regions.
    var points: [SIMD3<Float>]
    var distances: [Float]
    var regions: [SCHeadRegion]
    var stats: [SCHeadRegion: RegionStats]
    var mirrored: Bool
    /// Where the lens numbers came from: the depth picture's own, or the color image's.
    var lens: String
    /// Apple mask vs depth: for each mask point, (depth reading − mask distance) along the
    /// camera's view, in meters. + = the real face is behind the mask (the mask floats in
    /// front of it). Lower quarter, middle (median) and upper quarter; nil if too few points.
    var maskGap: (low: Float, median: Float, high: Float, count: Int)?
    /// Depth correction, if asked for and it worked: moves Apple-placed head-space points onto
    /// the head (corrected = correction × point), with its fit error and point count.
    var correction: simd_float4x4?
    var snapRms: Float = 0
    var snapPoints = 0
}

/// What one depth frame needs, copied off the AR frame.
nonisolated struct DepthCheckInput: @unchecked Sendable {
    var depth: AVDepthData
    /// Camera lens numbers for the color image, and that image's size (pixels).
    var intrinsics: simd_float3x3
    var imageSize: CGSize
    /// Camera → world, and world → head space.
    var cameraToWorld: simd_float4x4
    var worldToHead: simd_float4x4
    /// Apple's face mask points in world space.
    var maskWorld: [SIMD3<Float>]
    /// Whether to work out a depth correction for Apple's pose.
    var correct: Bool
}

nonisolated final class DepthChecker: @unchecked Sendable {
    static let gate: Float = 0.02          // points farther than 2 cm from the head aren't head
    static let pixelStep = 2               // use every 2nd depth pixel each way
    static let headRadius: Float = 0.2     // ignore points farther than this from the head center
    // Depth correction: snap with pairs up to 2 cm apart at first, narrowing to 4 mm
    static let snapStartGate: Float = 0.02
    static let snapEndGate: Float = 0.004
    static let snapIterations = 16
    static let snapMaxPoints = 4000
    static let snapMinPoints = 300
    static let snapMaxRms: Float = 0.004

    private let surface: SCHeadSurfaceCheck
    /// Whether depth pixels need flipping left-right to match ARKit's space. Decided
    /// automatically from the first few frames (whichever fits the head better).
    private var mirrorVotes = (plain: 0, flipped: 0)
    private var mirror: Bool?
    private let queue = DispatchQueue(label: "DepthChecker")
    private let busy = OSAllocatedUnfairLock(initialState: false)

    init(shape: Data) throws {
        let model = try HeadModelLoader.shared.get()
        surface = SCHeadSurfaceCheck(model: model, shape: shape)
    }

    /// Measures a frame in the background, unless one is still being measured (then skips it,
    /// so the check never falls behind the live picture).
    func submit(_ input: DepthCheckInput, done: @escaping @Sendable (DepthCheckFrame) -> Void) {
        let start = busy.withLock { isBusy -> Bool in
            if isBusy { return false }
            isBusy = true
            return true
        }
        guard start else { return }
        queue.async { [self] in
            let frame = measure(input)
            busy.withLock { $0 = false }
            done(frame)
        }
    }

    private func measure(_ input: DepthCheckInput) -> DepthCheckFrame {
        if let mirror {
            return measure(input, mirrored: mirror)
        }
        // Not decided yet: try both, vote for the one with more points on the head
        let plain = measure(input, mirrored: false)
        let flipped = measure(input, mirrored: true)
        let close = { (f: DepthCheckFrame) in zip(f.distances, f.regions).filter { abs($0.0) < 0.005 && $0.1 != SCHeadRegion.none }.count }
        if close(plain) >= close(flipped) { mirrorVotes.plain += 1 } else { mirrorVotes.flipped += 1 }
        if mirrorVotes.plain + mirrorVotes.flipped >= 5 { mirror = mirrorVotes.flipped > mirrorVotes.plain }
        return close(plain) >= close(flipped) ? plain : flipped
    }

    private func measure(_ input: DepthCheckInput, mirrored: Bool) -> DepthCheckFrame {
        let depth = input.depth.depthDataType == kCVPixelFormatType_DepthFloat32
            ? input.depth : input.depth.converting(toDepthDataType: kCVPixelFormatType_DepthFloat32)
        let map = depth.depthDataMap
        CVPixelBufferLockBaseAddress(map, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(map, .readOnly) }
        let width = CVPixelBufferGetWidth(map), height = CVPixelBufferGetHeight(map)
        let rowBytes = CVPixelBufferGetBytesPerRow(map)
        guard let base = CVPixelBufferGetBaseAddress(map) else {
            return DepthCheckFrame(points: [], distances: [], regions: [], stats: [:], mirrored: mirrored,
                                   lens: "none", maskGap: nil)
        }

        // Lens numbers (focal lengths fx, fy and center cx, cy) for the depth picture.
        // Best: the depth picture's own calibration. Otherwise, the color image's, assuming the
        // color image is the depth picture's full width, cropped top and bottom (16:9 from 4:3).
        let fx, fy, cx, cy: Float
        let lens: String
        if let calibration = depth.cameraCalibrationData {
            let k = calibration.intrinsicMatrix
            let reference = calibration.intrinsicMatrixReferenceDimensions
            let sx = Float(width) / Float(reference.width), sy = Float(height) / Float(reference.height)
            fx = k.columns.0.x * sx; fy = k.columns.1.y * sy
            cx = k.columns.2.x * sx; cy = k.columns.2.y * sy
            lens = "depth lens"
        } else {
            let scale = Float(width) / Float(input.imageSize.width)
            let k = input.intrinsics
            fx = k.columns.0.x * scale; fy = k.columns.1.y * scale
            cx = k.columns.2.x * scale
            cy = k.columns.2.y * scale + (Float(height) - Float(input.imageSize.height) * scale) / 2
            lens = "color lens"
        }
        let cameraToHead = input.worldToHead * input.cameraToWorld

        // Apple mask vs depth: project each mask point into the depth picture and compare
        // its distance from the camera with the depth reading there (middle of a 3×3 patch).
        let worldToCamera = input.cameraToWorld.inverse
        var gaps = [Float]()
        for m in input.maskWorld {
            let c = worldToCamera * SIMD4(m, 1)
            let z = -c.z                       // distance in front of the camera
            guard z > 0.1 else { continue }
            var u = c.x / z * fx + cx
            let v = -c.y / z * fy + cy
            if mirrored { u = Float(width - 1) - u }
            let iu = Int(u.rounded()), iv = Int(v.rounded())
            guard iu >= 1, iv >= 1, iu < width - 1, iv < height - 1 else { continue }
            var patch = [Float]()
            for dv in -1...1 {
                let row = base.advanced(by: (iv + dv) * rowBytes).assumingMemoryBound(to: Float32.self)
                for du in -1...1 {
                    let d = row[iu + du]
                    if d > 0.1 && d < 1.2 { patch.append(d) }
                }
            }
            guard patch.count >= 5 else { continue }
            patch.sort()
            let gap = patch[patch.count / 2] - z
            if abs(gap) < 0.03 { gaps.append(gap) }   // farther = background or hair at the mask's edge
        }
        var maskGap: (Float, Float, Float, Int)?
        if gaps.count >= 100 {
            gaps.sort()
            maskGap = (gaps[gaps.count / 4], gaps[gaps.count / 2], gaps[gaps.count * 3 / 4], gaps.count)
        }

        var points = [SIMD3<Float>]()
        points.reserveCapacity(width * height / (Self.pixelStep * Self.pixelStep) / 4)
        for v in stride(from: 0, to: height, by: Self.pixelStep) {
            let row = base.advanced(by: v * rowBytes).assumingMemoryBound(to: Float32.self)
            for u in stride(from: 0, to: width, by: Self.pixelStep) {
                let d = row[u]
                guard d > 0.1 && d < 1.2 else { continue }   // also skips NaN (no reading)
                let pu = mirrored ? Float(width - 1 - u) : Float(u)
                // Pixel → camera space (x right, y up, z toward the viewer; the scene is at -z)
                let camera = SIMD4<Float>((pu - cx) * d / fx, -(Float(v) - cy) * d / fy, -d, 1)
                let h = cameraToHead * camera
                let p = SIMD3(h.x, h.y, h.z)
                if simd_length(p) < Self.headRadius { points.append(p) }
            }
        }

        // Depth correction: snap a sample of the points onto the head's firm parts, then
        // move all points by the result (so the numbers below show the corrected pose)
        var correction: simd_float4x4?
        var snapRms: Float = 0, snapCount = 0
        if input.correct && !points.isEmpty {
            let step = max(1, points.count / Self.snapMaxPoints)
            var sample = [Float]()
            sample.reserveCapacity(points.count / step * 3 + 3)
            for i in stride(from: 0, to: points.count, by: step) {
                sample += [points[i].x, points[i].y, points[i].z]
            }
            let snap = surface.snap(points: sample.withUnsafeBufferPointer { Data(buffer: $0) },
                                    startGate: Self.snapStartGate, endGate: Self.snapEndGate,
                                    iterations: Self.snapIterations)
            snapRms = snap.rmsError
            snapCount = snap.usedPointCount
            if snapCount >= Self.snapMinPoints && snapRms < Self.snapMaxRms {
                let c = snap.correction
                correction = c
                points = points.map { p in
                    let q = c * SIMD4(p, 1)
                    return SIMD3(q.x, q.y, q.z)
                }
            }
        }

        // SIMD3<Float> is padded to 16 bytes; pack as plain x, y, z
        var packed = [Float]()
        packed.reserveCapacity(points.count * 3)
        for p in points { packed += [p.x, p.y, p.z] }
        let distanceData = NSMutableData(), regionData = NSMutableData()
        surface.measure(points: packed.withUnsafeBufferPointer { Data(buffer: $0) },
                        gate: Self.gate, distances: distanceData, regions: regionData)
        let distances = (distanceData as Data).floats
        let regions = [UInt8](regionData as Data).map { SCHeadRegion(rawValue: $0) ?? SCHeadRegion.none }

        var sums: [SCHeadRegion: (sq: Float, sum: Float, n: Int)] = [:]
        for (d, r) in zip(distances, regions) where r != SCHeadRegion.none {
            var s = sums[r] ?? (0, 0, 0)
            s.sq += d * d; s.sum += d; s.n += 1
            sums[r] = s
        }
        var stats: [SCHeadRegion: RegionStats] = [:]
        for (r, s) in sums where s.n > 0 {
            stats[r] = RegionStats(rms: (s.sq / Float(s.n)).squareRoot(), mean: s.sum / Float(s.n), count: s.n)
        }
        return DepthCheckFrame(points: points, distances: distances, regions: regions,
                               stats: stats, mirrored: mirrored,
                               lens: "\(lens) \(width)×\(height)", maskGap: maskGap,
                               correction: correction, snapRms: snapRms, snapPoints: snapCount)
    }
}
