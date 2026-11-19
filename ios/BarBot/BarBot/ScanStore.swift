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

/// One saved scan file. Plain data, so usable from any thread (e.g. during a merge).
nonisolated struct SavedScan: Identifiable, Hashable, Sendable {
    let url: URL
    let date: Date
    let sizeBytes: Int

    var id: URL { url }
    /// File name without ".ply", e.g. "scan-2026-11-19-143205".
    var name: String { url.deletingPathExtension().lastPathComponent }
}

enum ScanStoreError: LocalizedError {
    case writeFailed
    case emptyName
    case nameTaken(String)
    case renameFailed

    var errorDescription: String? {
        switch self {
        case .writeFailed: "The scan could not be saved."
        case .emptyName: "Please enter a name."
        case .nameTaken(let name): "A scan named \"\(name)\" already exists."
        case .renameFailed: "The scan could not be renamed."
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

    /// Writes a point cloud to a new file named after the current time and an optional
    /// label, e.g. "scan-2026-11-19-143205-front.ply" or "merged-2026-11-19-143205.ply".
    @discardableResult
    func save(_ pointCloud: SCPointCloud, prefix: String = "scan", label: String? = nil) throws -> URL {
        var name = "\(prefix)-\(fileNameFormatter.string(from: Date()))"
        if let label, !label.isEmpty { name += "-\(label)" }
        name += ".ply"
        let url = folder.appending(path: name)
        // StandardCyborg's own writer: positions, surface directions (normals),
        // colors, point sizes, and gravity ("which way is up").
        guard pointCloud.writeToPLY(atPath: url.path) else {
            throw ScanStoreError.writeFailed
        }
        reload()
        return url
    }

    /// Writes a point cloud to a file with a name you chose, e.g. "bryson-front-cap.ply".
    @discardableResult
    func save(_ pointCloud: SCPointCloud, named name: String) throws -> URL {
        let url = try urlForNewName(name)
        guard pointCloud.writeToPLY(atPath: url.path) else {
            throw ScanStoreError.writeFailed
        }
        reload()
        return url
    }

    /// Gives a saved scan a new name (keeps its date and contents).
    func rename(_ scan: SavedScan, to name: String) throws {
        let cleaned = Self.cleanName(name)
        guard cleaned != scan.name else { return }
        let url = try urlForNewName(cleaned)
        do {
            try FileManager.default.moveItem(at: scan.url, to: url)
        } catch {
            throw ScanStoreError.renameFailed
        }
        reload()
    }

    /// Makes a typed name safe to use as a file name: trims spaces, replaces
    /// characters files can't have (/ and :), and drops a ".ply" you may have typed.
    static func cleanName(_ name: String) -> String {
        var cleaned = name.trimmingCharacters(in: .whitespacesAndNewlines)
        if cleaned.lowercased().hasSuffix(".ply") { cleaned = String(cleaned.dropLast(4)) }
        cleaned = cleaned.replacingOccurrences(of: "/", with: "-")
                         .replacingOccurrences(of: ":", with: "-")
        while cleaned.hasPrefix(".") { cleaned.removeFirst() }  // no hidden files
        return cleaned.trimmingCharacters(in: .whitespaces)
    }

    /// The file URL for a new name, after checking it's not empty or already used.
    private func urlForNewName(_ name: String) throws -> URL {
        let cleaned = Self.cleanName(name)
        guard !cleaned.isEmpty else { throw ScanStoreError.emptyName }
        let url = folder.appending(path: "\(cleaned).ply")
        guard !FileManager.default.fileExists(atPath: url.path) else {
            throw ScanStoreError.nameTaken(cleaned)
        }
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
