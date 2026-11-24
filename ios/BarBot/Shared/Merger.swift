//
//  Merger.swift
//  Shared by BarBot (test app) and HairBarbot (user app)
//
//  Merges partial scans of the same head in order. The first scan stays put; each
//  next scan is lined up onto everything merged so far (StandardCyborg fork:
//  SCPointCloudMerging, which stands scans upright by gravity, then searches turns).
//

import Foundation
import StandardCyborgFusion

// MARK: - Results

/// How well one scan lined up onto the scans before it.
struct MergeStepReport: Identifiable {
    let id = UUID()
    let scanName: String
    /// Share of the scan's points that ended up on the existing surface (0–1).
    let overlap: Float
    /// Typical distance between the matched surfaces, in millimeters.
    let fitMillimeters: Float
    /// Turn about the vertical axis that was chosen, in degrees.
    let yawDegrees: Float
    /// Share of points sitting clearly in front of the other scan's surface (0–1, ~0 when right).
    let seeThrough: Float
    /// overlap − 2 × seeThrough: how the merger ranked it.
    let score: Float
    /// True if it started from the recorded pose (scans from the same view), false if from the full search.
    let usedRecordedPose: Bool
    /// Best alternative at a clearly different turn.
    let runnerUpOverlap: Float
    let runnerUpScore: Float
    let runnerUpYawDegrees: Float
    /// True if another turn scored almost as well, so the choice may be wrong.
    let isAmbiguous: Bool
    /// Where the body was cut off for lining up (cm below the top of the head; 0 = not cut),
    /// for this scan and for the scans it was lined up onto.
    let scanCutCentimeters: Float
    let baseCutCentimeters: Float

    /// True if this step looks wrong enough to ask the person to check or redo it.
    var looksDoubtful: Bool { isAmbiguous || overlap < 0.15 || seeThrough > 0.05 }
}

/// A finished merge, ready to view and save.
struct MergeOutcome: Identifiable, @unchecked Sendable {
    let id = UUID()
    let pointCloud: SCPointCloud
    let baseScanName: String
    let steps: [MergeStepReport]
    let seconds: Double
}

enum Merger {
    enum MergeError: LocalizedError {
        case unreadable(String)

        var errorDescription: String? {
            switch self {
            case .unreadable(let name): "Couldn't open \(name)."
            }
        }
    }

    /// Merges scans in the given order. Runs off the main thread.
    /// `startsFromSameView` says which scans began from the same view as the first one
    /// (phone on a stand, person facing it): those start lining up from where they were
    /// recorded instead of searching every turn.
    /// `progress` gets a short status message before each step.
    nonisolated static func merge(_ scans: [SavedScan],
                                  startsFromSameView: @escaping @Sendable (SavedScan) -> Bool = { _ in false },
                                  progress: @escaping @Sendable (String) async -> Void) async throws -> MergeOutcome {
        let start = Date()
        guard let first = scans.first else { throw MergeError.unreadable("no scans") }

        await progress("Opening \(first.name)…")
        guard var merged = SCPointCloud(plyPath: first.url.path) else {
            throw MergeError.unreadable(first.name)
        }

        var steps: [MergeStepReport] = []
        for (index, scan) in scans.enumerated().dropFirst() {
            await progress("Lining up scan \(index + 1) of \(scans.count)…")
            guard let next = SCPointCloud(plyPath: scan.url.path) else {
                throw MergeError.unreadable(scan.name)
            }

            let alignment = SCPointCloudMerging.align(next, onto: merged,
                                                      startingFromRecordedPose: startsFromSameView(scan))
            merged = SCPointCloudMerging.merge(next, transformedBy: alignment.transform, into: merged)

            steps.append(MergeStepReport(scanName: scan.name,
                                         overlap: alignment.overlap,
                                         fitMillimeters: alignment.rmsError * 1000,
                                         yawDegrees: alignment.yawDegrees,
                                         seeThrough: alignment.seeThrough,
                                         score: alignment.score,
                                         usedRecordedPose: alignment.usedRecordedPose,
                                         runnerUpOverlap: alignment.runnerUpOverlap,
                                         runnerUpScore: alignment.runnerUpScore,
                                         runnerUpYawDegrees: alignment.runnerUpYawDegrees,
                                         isAmbiguous: alignment.isAmbiguous,
                                         scanCutCentimeters: alignment.sourceBodyCutDepth * 100,
                                         baseCutCentimeters: alignment.targetBodyCutDepth * 100))
        }

        return MergeOutcome(pointCloud: merged,
                            baseScanName: first.name,
                            steps: steps,
                            seconds: Date().timeIntervalSince(start))
    }
}
