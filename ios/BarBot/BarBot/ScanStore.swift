//
//  ScanStore.swift
//  BarBot
//
//  Saves, lists, loads and deletes scan files.
//
//  Scans are PLY files (a common 3D point file format) in the app's
//  Documents/Scans folder. That folder also shows up in the iPhone's
//  Files app under "On My iPhone → BarBot", so scans can be AirDropped.
//

import Foundation
import Observation
import StandardCyborgFusion

/// One saved scan file.
struct SavedScan: Identifiable, Hashable {
    let url: URL
    let date: Date
    let sizeBytes: Int

    var id: URL { url }
    /// File name without ".ply", e.g. "scan-2026-11-19-143205".
    var name: String { url.deletingPathExtension().lastPathComponent }
}

enum ScanStoreError: LocalizedError {
    case writeFailed

    var errorDescription: String? {
        switch self {
        case .writeFailed: "The scan could not be saved."
        }
    }
}

@Observable
final class ScanStore {
    /// Saved scans, newest first.
    private(set) var scans: [SavedScan] = []

    /// Documents/Scans
    let folder: URL = URL.documentsDirectory.appending(path: "Scans", directoryHint: .isDirectory)

    private let fileNameFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd-HHmmss"
        return formatter
    }()

    init() {
        try? FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        reload()
    }

    /// Re-reads the folder (e.g. after a file was added or deleted).
    func reload() {
        let keys: Set<URLResourceKey> = [.creationDateKey, .fileSizeKey]
        let urls = (try? FileManager.default.contentsOfDirectory(at: folder,
                                                                 includingPropertiesForKeys: Array(keys))) ?? []
        scans = urls
            .filter { $0.pathExtension.lowercased() == "ply" }
            .map { url in
                let values = try? url.resourceValues(forKeys: keys)
                return SavedScan(url: url,
                                 date: values?.creationDate ?? .distantPast,
                                 sizeBytes: values?.fileSize ?? 0)
            }
            .sorted { $0.date > $1.date }
    }

    /// Writes a finished scan to a new file named after the current time.
    @discardableResult
    func save(_ pointCloud: SCPointCloud) throws -> URL {
        let name = "scan-\(fileNameFormatter.string(from: Date())).ply"
        let url = folder.appending(path: name)
        // StandardCyborg's own writer: positions, surface directions (normals),
        // colors, point sizes, and gravity ("which way is up").
        guard pointCloud.writeToPLY(atPath: url.path) else {
            throw ScanStoreError.writeFailed
        }
        reload()
        return url
    }

    /// Reads a saved scan back into memory (nil if the file can't be read).
    func load(_ scan: SavedScan) -> SCPointCloud? {
        SCPointCloud(plyPath: scan.url.path)
    }

    func delete(_ scan: SavedScan) {
        try? FileManager.default.removeItem(at: scan.url)
        reload()
    }
}
