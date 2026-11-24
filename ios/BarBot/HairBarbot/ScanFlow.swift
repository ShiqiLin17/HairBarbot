//
//  ScanFlow.swift
//  HairBarbot
//
//  The guided head scan, step by step:
//    get ready → how it works → scan right → review → scan left → review merge
//    → scan top → review merge → fit the head model → save under a name.
//  "Redo" on a review screen repeats only the latest scan.
//
//  Accepted scans are kept as PLY files in Documents/CurrentScan (cleared when a
//  new scan starts), so nothing reaches the saved heads until the person taps Save.
//

import Foundation
import Observation
import StandardCyborgFusion

/// The three scans, in order. Scan 1 (right) stays put; the others are lined up onto it.
enum ScanPass: Int, CaseIterable, Identifiable {
    case right, left, top

    var id: Int { rawValue }
    var fileName: String { ["right", "left", "top"][rawValue] + ".ply" }
    /// For the step indicator.
    var shortTitle: String { ["Right", "Left", "Top"][rawValue] }
}

enum ScanStep: Equatable {
    case prep
    case howTo
    case scan(ScanPass)
    case review(ScanPass)
    case save
    case saved(name: String)
}

@Observable
final class ScanFlow {
    var step: ScanStep = .prep
    /// Name to fill in on the save screen (set when rescanning someone).
    let suggestedName: String

    /// What the current review screen shows: the scan (right) or the merge so far (left, top).
    private(set) var reviewCloud: SCPointCloud?
    /// Shown on a merge review when the scans may not have lined up.
    private(set) var reviewWarning: String?
    private(set) var isMerging = false
    private(set) var reviewError: String?

    private(set) var isFitting = false
    /// The fitted head, in the model's own head space (facing +z), for the save screen.
    private(set) var fittedMesh: HeadMesh?
    private(set) var fitError: String?
    private var fit: HeadFit?

    private let folder = URL.documentsDirectory.appending(path: "CurrentScan", directoryHint: .isDirectory)
    private var mergedURL: URL { folder.appending(path: "merged.ply") }
    /// Bumped whenever the review changes, so a slow merge for an old review is ignored.
    private var reviewID = 0

    /// No file work here: SwiftUI may create (and throw away) extra copies while redrawing.
    init(suggestedName: String = "") {
        self.suggestedName = suggestedName
    }

    /// Clears scans left over from an earlier, unfinished flow. Call once when the flow opens.
    func begin() {
        try? FileManager.default.removeItem(at: folder)
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    }

    // MARK: - Moving through the steps

    /// A scan finished: keep it and show its review.
    func captured(_ pointCloud: SCPointCloud, for pass: ScanPass) {
        let url = folder.appending(path: pass.fileName)
        try? FileManager.default.removeItem(at: url)
        guard pointCloud.writeToPLY(atPath: url.path) else {
            reviewError = "The scan couldn't be saved on this phone. Please try again."
            step = .review(pass)
            return
        }
        step = .review(pass)
        prepareReview(for: pass, scan: pointCloud)
    }

    /// "Looks good" on a review screen.
    func approve(_ pass: ScanPass) {
        switch pass {
        case .right: step = .scan(.left)
        case .left: step = .scan(.top)
        case .top:
            step = .save
            startFit()
        }
    }

    /// "Redo" on a review screen: repeat that scan only.
    func redo(_ pass: ScanPass) {
        reviewID += 1
        reviewCloud = nil
        reviewWarning = nil
        reviewError = nil
        isMerging = false
        step = .scan(pass)
    }

    /// Fitting failed: start the scans over.
    func startOver() {
        fit = nil
        fittedMesh = nil
        fitError = nil
        redo(.right)
    }

    // MARK: - Reviews

    /// Reviews show only the head: the shirt and shoulders aren't part of the head model
    /// and only distract from checking the face and ears.
    private func prepareReview(for pass: ScanPass, scan: SCPointCloud) {
        reviewID += 1
        let id = reviewID
        reviewWarning = nil
        reviewError = nil
        reviewCloud = nil
        isMerging = pass != .right
        guard pass != .right else {
            let box = CloudBox(cloud: scan)
            Task {
                let head = await Task.detached(priority: .userInitiated) {
                    CloudBox(cloud: SCPointCloudMerging.headOnly(box.cloud))
                }.value
                if id == reviewID { reviewCloud = head.cloud }
            }
            return
        }
        let scans = ScanPass.allCases.prefix(through: pass.rawValue).map { savedScan(folder.appending(path: $0.fileName)) }
        // The left scan starts like the right one: facing the phone on its stand, so it starts
        // lining up from where it was recorded. The top scan is handheld: full search.
        let sameView = folder.appending(path: ScanPass.left.fileName)
        Task {
            do {
                let (outcome, head) = try await Task.detached(priority: .userInitiated) {
                    let outcome = try await Merger.merge(scans, startsFromSameView: { $0.url == sameView }) { _ in }
                    return (outcome, CloudBox(cloud: SCPointCloudMerging.headOnly(outcome.pointCloud)))
                }.value
                guard id == reviewID else { return }
                reviewCloud = head.cloud
                if let last = outcome.steps.last, last.looksDoubtful {
                    reviewWarning = "The scans didn't line up confidently. Look closely, or redo the \(pass == .left ? "left" : "top") scan."
                }
                if pass == .top { try? FileManager.default.removeItem(at: mergedURL) }
                if pass == .top, !outcome.pointCloud.writeToPLY(atPath: mergedURL.path) {
                    reviewError = "The merged scan couldn't be saved on this phone. Please try again."
                }
            } catch {
                guard id == reviewID else { return }
                reviewError = "The scans couldn't be put together. Please redo the last scan."
            }
            if id == reviewID { isMerging = false }
        }
    }

    // MARK: - Fitting and saving

    private func startFit() {
        fit = nil
        fittedMesh = nil
        fitError = nil
        isFitting = true
        let merged = savedScan(mergedURL)
        Task {
            do {
                let (fit, mesh) = try await Task.detached(priority: .userInitiated) {
                    let fit = try HeadFitter.fit(merged)
                    return (fit, try Self.headSpaceMesh(for: fit))
                }.value
                if Self.isUsable(fit.result) {
                    self.fit = fit
                    fittedMesh = mesh
                } else {
                    fitError = "We couldn't build a head model from these scans. Please scan again."
                }
            } catch {
                fitError = "We couldn't build a head model from these scans. Please scan again."
            }
            isFitting = false
        }
    }

    /// True if a fit looks like a real head: it has a shape and its typical error is small.
    /// (Good capped scans fit to a few mm; 15 mm means it latched onto the wrong thing.)
    private static func isUsable(_ result: SCHeadFitResult) -> Bool {
        result.shapeCoefficients.count > 0 && result.rmsError.isFinite && result.rmsError < 0.015
    }

    nonisolated private static func headSpaceMesh(for fit: HeadFit) throws -> HeadMesh {
        let model = try HeadModelLoader.shared.get()
        return HeadMesh(vertices: model.vertices(forShape: fit.result.shapeCoefficients).floats,
                        triangles: model.triangles.uint32s)
    }

    var canSave: Bool { fit != nil }

    /// Saves the fitted head under `name` (replacing one with the same name), and keeps
    /// the merged scan as Documents/Scans/<name>-merged.ply.
    func save(named name: String, to heads: HeadStore) throws {
        guard let fit else { return }
        let cleaned = ScanStore.cleanName(name)
        guard !cleaned.isEmpty else { throw HeadStoreError.emptyName }

        let scansFolder = URL.documentsDirectory.appending(path: "Scans", directoryHint: .isDirectory)
        try? FileManager.default.createDirectory(at: scansFolder, withIntermediateDirectories: true)
        let scanURL = scansFolder.appending(path: "\(cleaned)-merged.ply")
        try? FileManager.default.removeItem(at: scanURL)
        do {
            try FileManager.default.copyItem(at: mergedURL, to: scanURL)
        } catch {
            throw HeadStoreError.writeFailed(error.localizedDescription)
        }

        let head = try heads.save(fit.result, from: savedScan(scanURL), named: cleaned)
        try? FileManager.default.removeItem(at: folder)
        step = .saved(name: head.name)
    }

    /// Throws away the scans in progress (the X button).
    func discard() {
        reviewID += 1
        try? FileManager.default.removeItem(at: folder)
    }

    /// Carries a point cloud to and from a background task.
    private struct CloudBox: @unchecked Sendable { let cloud: SCPointCloud }

    private func savedScan(_ url: URL) -> SavedScan {
        SavedScan(url: url, date: Date(), sizeBytes: 0)
    }
}

/// Deletes a saved person: their head and their merged scan.
extension HeadStore {
    func deletePerson(_ head: SavedHead) {
        let scan = URL.documentsDirectory.appending(path: "Scans/\(head.name)-merged.ply")
        try? FileManager.default.removeItem(at: scan)
        delete(head)
    }
}
