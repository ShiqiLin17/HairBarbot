//
//  TrackRecorder.swift
//  BarBot
//
//  The tracking test recorder (Tracking plan, step 6). "Record" collects about
//  10 seconds of tracking, then sums it up as numbers:
//
//   - Steadiness: how much the head center and the back of the head wander (spread)
//     and twitch from frame to frame (jitter), for three versions of the pose:
//       Apple  = Apple's face pose + line-up
//       fixed  = + the depth fix
//       smooth = + the One Euro filter
//     (all three are recorded at once, whatever the buttons are set to).
//   - Region errors: the depth check's distances, pooled over the whole recording,
//     so the depth camera's frame-to-frame noise mostly averages out.
//   - Apple's error: how far the depth fix had to move Apple's pose.
//   - The average turn / nod / tilt (for the known-turn test) and the strongest
//     expression (for the expression test).
//
//  Each run is added as a row to Documents/TrackLogs/track-log.csv (visible in the
//  Files app), labeled with what you were doing.
//

import Foundation
import simd
import StandardCyborgFusion

/// The three versions of the head pose for one frame, in phone space.
struct RecordedPose {
    var apple: simd_float4x4
    var fixed: simd_float4x4
    var smooth: simd_float4x4
}

final class TrackRecorder {
    static let duration: TimeInterval = 10
    /// A point at the back of the head, in head space (FLAME's back is about 15 cm behind the center).
    static let backOfHead = SIMD3<Float>(0, 0.02, -0.15)

    let label: String
    let start = Date()
    private var poses: [RecordedPose] = []
    private var lostFrames = 0
    private var expressionMax: Float = 0
    private var regionSums: [SCHeadRegion: (sum: Float, squares: Float, count: Int)] = [:]
    private var fixMillimeters: [Float] = []
    private var fixDegrees: [Float] = []
    private var snapRms: [Float] = []
    private var maskGaps: [Float] = []
    private var depthFrames = 0

    init(label: String) { self.label = label }

    var progress: Double { min(1, Date().timeIntervalSince(start) / Self.duration) }
    var isDone: Bool { Date().timeIntervalSince(start) >= Self.duration }

    func add(_ pose: RecordedPose, expression: Float) {
        poses.append(pose)
        expressionMax = max(expressionMax, expression)
    }

    func addLostFrame() { lostFrames += 1 }

    func add(_ depth: DepthCheckFrame) {
        depthFrames += 1
        for (region, stats) in depth.stats {
            var s = regionSums[region] ?? (0, 0, 0)
            s.sum += stats.mean * Float(stats.count)
            s.squares += stats.rms * stats.rms * Float(stats.count)
            s.count += stats.count
            regionSums[region] = s
        }
        if let c = depth.correction {
            let shift = simd_length(SIMD3(c.columns.3.x, c.columns.3.y, c.columns.3.z)) * 1000
            fixMillimeters.append(shift)
            fixDegrees.append(Self.angleDegrees(c))
            snapRms.append(depth.snapRms * 1000)
        }
        if let gap = depth.maskGap { maskGaps.append(gap.median * 1000) }
    }

    // MARK: Summary

    func summary(head: String, fixOn: Bool, smoothOn: Bool) -> TrackRunSummary {
        var s = TrackRunSummary(date: start, label: label, head: head, fixOn: fixOn, smoothOn: smoothOn)
        s.seconds = Date().timeIntervalSince(start)
        s.frames = poses.count
        s.lostFrames = lostFrames
        s.depthFrames = depthFrames
        s.expressionMax = expressionMax
        if !poses.isEmpty {
            let angles = poses.map { HeadPose(transform: $0.smooth).angles }
            s.turn = Self.mean(angles.map(\.turn))
            s.nod = Self.mean(angles.map(\.nod))
            s.tilt = Self.mean(angles.map(\.tilt))
            s.distanceCm = Self.mean(poses.map { -$0.smooth.columns.3.z }) * 100
        }
        s.apple = Self.steadiness(poses.map(\.apple))
        s.fixed = Self.steadiness(poses.map(\.fixed))
        s.smooth = Self.steadiness(poses.map(\.smooth))
        s.appleErrorMeanMm = Self.mean(fixMillimeters)
        s.appleErrorMaxMm = fixMillimeters.max() ?? 0
        s.appleErrorMeanDeg = Self.mean(fixDegrees)
        s.snapRmsMm = Self.mean(snapRms)
        s.maskGapMm = Self.mean(maskGaps)
        for (region, sums) in regionSums where sums.count > 0 {
            let n = Float(sums.count)
            s.regions[Self.name(region)] = RegionResult(meanMm: sums.sum / n * 1000,
                                                        rmsMm: (sums.squares / n).squareRoot() * 1000,
                                                        points: sums.count)
        }
        return s
    }

    /// Spread and jitter of a series of poses.
    private static func steadiness(_ series: [simd_float4x4]) -> Steadiness {
        guard series.count >= 2 else { return Steadiness() }
        func point(_ m: simd_float4x4, _ p: SIMD3<Float>) -> SIMD3<Float> {
            let q = m * SIMD4(p, 1)
            return SIMD3(q.x, q.y, q.z)
        }
        func spread(_ points: [SIMD3<Float>]) -> Float {
            let center = points.reduce(SIMD3<Float>.zero, +) / Float(points.count)
            return (points.map { simd_length_squared($0 - center) }.reduce(0, +) / Float(points.count)).squareRoot()
        }
        func jitter(_ points: [SIMD3<Float>]) -> Float {
            let steps = zip(points.dropFirst(), points).map { simd_length_squared($0 - $1) }
            return (steps.reduce(0, +) / Float(steps.count)).squareRoot()
        }
        let centers = series.map { point($0, .zero) }
        let backs = series.map { point($0, backOfHead) }
        // Angles: spread of each frame's turn from the average turn; jitter between frames
        let angles = series.map { HeadPose(transform: $0).angles }
        let angleSpread = (variance(angles.map(\.turn)) + variance(angles.map(\.nod)) + variance(angles.map(\.tilt))).squareRoot()
        let angleSteps = zip(series.dropFirst(), series).map { angleDegrees($1.inverse * $0) }
        let angleJitter = (angleSteps.map { $0 * $0 }.reduce(0, +) / Float(angleSteps.count)).squareRoot()
        return Steadiness(centerSpreadMm: spread(centers) * 1000, backSpreadMm: spread(backs) * 1000,
                          centerJitterMm: jitter(centers) * 1000, backJitterMm: jitter(backs) * 1000,
                          angleSpreadDeg: angleSpread, angleJitterDeg: angleJitter)
    }

    private static func mean(_ values: [Float]) -> Float {
        values.isEmpty ? 0 : values.reduce(0, +) / Float(values.count)
    }

    private static func variance(_ values: [Float]) -> Float {
        let m = mean(values)
        return mean(values.map { ($0 - m) * ($0 - m) })
    }

    /// Rotation angle of a rigid transform, in degrees.
    static func angleDegrees(_ m: simd_float4x4) -> Float {
        let trace = m.columns.0.x + m.columns.1.y + m.columns.2.z
        return acos(max(-1, min(1, (trace - 1) / 2))) * 180 / .pi
    }

    static func name(_ region: SCHeadRegion) -> String {
        switch region {
        case .face: "face"
        case .forehead: "forehead"
        case .scalp: "scalp"
        case .leftEar: "left_ear"
        case .rightEar: "right_ear"
        case .other: "other"
        default: "none"
        }
    }
}

// MARK: - Results

struct Steadiness: Codable {
    /// How far the head center / back of the head wander from their average position (mm, rms).
    var centerSpreadMm: Float = 0
    var backSpreadMm: Float = 0
    /// How far they move from one frame to the next (mm, rms).
    var centerJitterMm: Float = 0
    var backJitterMm: Float = 0
    /// Same for the angles (degrees).
    var angleSpreadDeg: Float = 0
    var angleJitterDeg: Float = 0
}

struct RegionResult: Codable {
    var meanMm: Float
    var rmsMm: Float
    var points: Int
}

struct TrackRunSummary: Codable, Identifiable {
    var date: Date
    var label: String
    var head: String
    var fixOn: Bool
    var smoothOn: Bool
    var seconds: Double = 0
    var frames = 0
    var lostFrames = 0
    var depthFrames = 0
    var distanceCm: Float = 0
    var turn: Float = 0, nod: Float = 0, tilt: Float = 0
    var apple = Steadiness(), fixed = Steadiness(), smooth = Steadiness()
    var appleErrorMeanMm: Float = 0, appleErrorMaxMm: Float = 0, appleErrorMeanDeg: Float = 0
    var snapRmsMm: Float = 0
    var maskGapMm: Float = 0
    var regions: [String: RegionResult] = [:]
    var expressionMax: Float = 0

    var id: Date { date }

    /// The results as readable lines, for the screen.
    var text: String {
        func f(_ v: Float) -> String { String(format: "%.1f", v) }
        func region(_ name: String) -> String {
            guard let r = regions[name] else { return "\(name) —" }
            return String(format: "%@ %+.1f (rms %.1f)", name, r.meanMm, r.rmsMm)
        }
        func steady(_ name: String, _ s: Steadiness) -> String {
            "\(name)  center \(f(s.centerSpreadMm)) / \(f(s.centerJitterMm))   back \(f(s.backSpreadMm)) / \(f(s.backJitterMm))   angle \(String(format: "%.2f", s.angleSpreadDeg))° / \(String(format: "%.2f", s.angleJitterDeg))°"
        }
        return """
        \(label) · \(head) · \(String(format: "%.0f", seconds)) s · \(frames) frames (\(lostFrames) lost) · \(depthFrames) depth
        average pose: turn \(f(turn))°  nod \(f(nod))°  tilt \(f(tilt))°  \(String(format: "%.0f", distanceCm)) cm away
        strongest expression: \(String(format: "%.2f", expressionMax)) (0 = relaxed, 1 = full)

        STEADINESS — spread / frame-to-frame jitter (mm, degrees)
        \(steady("Apple ", apple))
        \(steady("fixed ", fixed))
        \(steady("smooth", smooth))

        APPLE'S ERROR (what the depth fix corrected)
        average \(f(appleErrorMeanMm)) mm / \(f(appleErrorMeanDeg))°, largest \(f(appleErrorMaxMm)) mm
        fix fit \(f(snapRmsMm)) mm · Apple mask vs depth \(f(maskGapMm)) mm

        REGION ERRORS, pooled — average (rms), mm; + = real surface outside the head
        \(region("face"))   \(region("forehead"))
        \(region("left_ear"))   \(region("right_ear"))
        \(region("scalp"))
        """
    }

    static let csvHeader = [
        "date", "label", "head", "fix", "smooth", "seconds", "frames", "lost_frames", "depth_frames",
        "distance_cm", "turn_deg", "nod_deg", "tilt_deg", "expression_max",
        "apple_center_spread_mm", "fixed_center_spread_mm", "smooth_center_spread_mm",
        "apple_back_spread_mm", "fixed_back_spread_mm", "smooth_back_spread_mm",
        "apple_center_jitter_mm", "fixed_center_jitter_mm", "smooth_center_jitter_mm",
        "apple_back_jitter_mm", "fixed_back_jitter_mm", "smooth_back_jitter_mm",
        "apple_angle_spread_deg", "fixed_angle_spread_deg", "smooth_angle_spread_deg",
        "apple_angle_jitter_deg", "fixed_angle_jitter_deg", "smooth_angle_jitter_deg",
        "apple_error_mean_mm", "apple_error_max_mm", "apple_error_mean_deg", "fix_fit_mm", "mask_gap_mm",
        "face_mean_mm", "face_rms_mm", "forehead_mean_mm", "forehead_rms_mm",
        "left_ear_mean_mm", "left_ear_rms_mm", "right_ear_mean_mm", "right_ear_rms_mm",
        "scalp_mean_mm", "scalp_rms_mm",
    ].joined(separator: ",")

    var csvRow: String {
        func f(_ v: Float) -> String { String(format: "%.2f", v) }
        func quoted(_ s: String) -> String { "\"" + s.replacingOccurrences(of: "\"", with: "\"\"") + "\"" }
        let r = { (name: String) -> [String] in
            guard let v = regions[name] else { return ["", ""] }
            return [f(v.meanMm), f(v.rmsMm)]
        }
        var cells: [String] = [
            ISO8601DateFormatter().string(from: date), quoted(label), quoted(head),
            fixOn ? "1" : "0", smoothOn ? "1" : "0", String(format: "%.1f", seconds),
            "\(frames)", "\(lostFrames)", "\(depthFrames)",
            f(distanceCm), f(turn), f(nod), f(tilt), f(expressionMax),
        ]
        let s = [apple, fixed, smooth]
        cells += s.map { f($0.centerSpreadMm) } + s.map { f($0.backSpreadMm) }
        cells += s.map { f($0.centerJitterMm) } + s.map { f($0.backJitterMm) }
        cells += s.map { f($0.angleSpreadDeg) } + s.map { f($0.angleJitterDeg) }
        cells += [f(appleErrorMeanMm), f(appleErrorMaxMm), f(appleErrorMeanDeg), f(snapRmsMm), f(maskGapMm)]
        cells += r("face") + r("forehead") + r("left_ear") + r("right_ear") + r("scalp")
        return cells.joined(separator: ",")
    }
}

/// The log of test runs: Documents/TrackLogs/track-log.csv.
enum TrackLog {
    static var url: URL {
        URL.documentsDirectory.appending(path: "TrackLogs", directoryHint: .isDirectory)
            .appending(path: "track-log.csv")
    }

    static func append(_ summary: TrackRunSummary) throws {
        let folder = url.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: url.path) {
            try (TrackRunSummary.csvHeader + "\n").write(to: url, atomically: true, encoding: .utf8)
        }
        let handle = try FileHandle(forWritingTo: url)
        defer { try? handle.close() }
        try handle.seekToEnd()
        try handle.write(contentsOf: Data((summary.csvRow + "\n").utf8))
    }
}
