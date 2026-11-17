//
//  DepthCamera.swift
//  BarBot
//
//  Talks to the front TrueDepth camera and reads distances from it.
//
//  Two parts:
//  - DepthCamera: what the screen talks to. Asks for camera permission,
//    starts the camera, and holds the latest distance and picture for the
//    screen to show.
//  - DepthWorker: does the camera work in the background, so the screen
//    never freezes. Receives ~30 depth maps per second.
//

import AVFoundation
import CoreGraphics
import CoreMedia
import CoreVideo
import Observation

/// What the screen uses. Lives on the main thread (the "UI thread").
@Observable
final class DepthCamera {
    /// A short message for the screen, e.g. "Running" or an error.
    var status = "Starting…"
    /// True if you tapped "Don't Allow" on the camera popup.
    var permissionDenied = false
    /// Latest distance to whatever is in the middle of the view, in meters.
    /// nil means "no good reading right now".
    var centerDistanceMeters: Float?
    /// Latest depth map as a gray picture (close = bright, far = dark).
    var depthImage: CGImage?
    /// While true, the number and picture stop updating so you can read them.
    var isHeld = false

    @ObservationIgnored private let worker = DepthWorker()

    func start() {
        Task {
            // Shows the "Allow camera?" popup the first time.
            // After that it just returns the answer you gave.
            let allowed = await AVCaptureDevice.requestAccess(for: .video)
            guard allowed else {
                permissionDenied = true
                status = "Camera access is off."
                return
            }

            // The worker calls this from the background; hop to the main
            // thread before changing anything the screen shows.
            // (stop() clears this again, so the two don't keep each other alive.)
            worker.onFrame = { [self] meters, image in
                Task { @MainActor in
                    guard !self.isHeld else { return }
                    self.centerDistanceMeters = meters
                    self.depthImage = image
                }
            }

            do {
                try worker.start()
                status = "Running"
            } catch {
                status = "Camera error: \(error.localizedDescription)"
            }
        }
    }

    func stop() {
        worker.onFrame = nil
        worker.stop()
    }
}

enum DepthCameraError: LocalizedError {
    case noTrueDepthCamera
    case cannotConnect

    var errorDescription: String? {
        switch self {
        case .noTrueDepthCamera: "This phone has no front TrueDepth camera."
        case .cannotConnect: "Could not connect to the TrueDepth camera."
        }
    }
}

/// The background camera worker. Everything here runs off the main thread.
nonisolated final class DepthWorker: NSObject, AVCaptureDepthDataOutputDelegate, @unchecked Sendable {
    /// Called with each new center distance (meters, or nil if unreadable)
    /// and the depth map drawn as a gray picture.
    var onFrame: (@Sendable (Float?, CGImage?) -> Void)?

    /// Distances drawn in the gray picture: this close = white, this far = black.
    static let nearestShown: Float = 0.15
    static let farthestShown: Float = 1.0

    /// The "camera session": connects the camera (input) to our code (output).
    private let session = AVCaptureSession()
    /// The output that hands us depth maps.
    private let depthOutput = AVCaptureDepthDataOutput()
    /// A background lane where depth maps arrive, one at a time.
    private let queue = DispatchQueue(label: "barbot.depth")
    private var frameCount = 0

    func start() throws {
        // 1. Find the front TrueDepth camera.
        guard let camera = AVCaptureDevice.default(.builtInTrueDepthCamera, for: .video, position: .front) else {
            throw DepthCameraError.noTrueDepthCamera
        }

        session.beginConfiguration()
        session.sessionPreset = .vga640x480

        // 2. Plug the camera into the session.
        let input = try AVCaptureDeviceInput(device: camera)
        guard session.canAddInput(input) else { throw DepthCameraError.cannotConnect }
        session.addInput(input)

        // 3. Ask the session to send us depth maps.
        guard session.canAddOutput(depthOutput) else { throw DepthCameraError.cannotConnect }
        session.addOutput(depthOutput)
        // Apple's built-in smoothing: fills small holes so the number is steadier.
        depthOutput.isFilteringEnabled = true
        depthOutput.setDelegate(self, callbackQueue: queue)

        // 4. Pick the sharpest depth format that gives true distances (meters).
        let depthFormats = camera.activeFormat.supportedDepthDataFormats.filter {
            CMFormatDescriptionGetMediaSubType($0.formatDescription) == kCVPixelFormatType_DepthFloat32
        }
        if let best = depthFormats.max(by: {
            CMVideoFormatDescriptionGetDimensions($0.formatDescription).width
                < CMVideoFormatDescriptionGetDimensions($1.formatDescription).width
        }) {
            try camera.lockForConfiguration()
            camera.activeDepthDataFormat = best
            camera.unlockForConfiguration()
        }

        session.commitConfiguration()

        // 5. Start. This takes a moment, so do it off the main thread.
        queue.async { self.session.startRunning() }
    }

    func stop() {
        queue.async { self.session.stopRunning() }
    }

    // Called ~30 times per second with a new depth map.
    func depthDataOutput(_ output: AVCaptureDepthDataOutput,
                         didOutput depthData: AVDepthData,
                         timestamp: CMTime,
                         connection: AVCaptureConnection) {
        // Make sure each cell holds a distance in meters (not "disparity").
        let depth = depthData.converting(toDepthDataType: kCVPixelFormatType_DepthFloat32)
        let map = depth.depthDataMap
        let meters = Self.centerDistance(of: map)
        let image = Self.grayImage(of: map)

        // Print about twice a second so the console stays readable.
        frameCount += 1
        if frameCount % 15 == 0 {
            if let meters {
                print(String(format: "center distance: %.1f cm", meters * 100))
            } else {
                print("center distance: no reading")
            }
        }

        onFrame?(meters, image)
    }

    /// The typical distance in a small square at the middle of the depth map.
    /// Uses the median (middle value) so one bad dot can't throw it off.
    static func centerDistance(of map: CVPixelBuffer, patchRadius: Int = 4) -> Float? {
        CVPixelBufferLockBaseAddress(map, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(map, .readOnly) }

        guard let base = CVPixelBufferGetBaseAddress(map) else { return nil }
        let width = CVPixelBufferGetWidth(map)
        let height = CVPixelBufferGetHeight(map)
        let bytesPerRow = CVPixelBufferGetBytesPerRow(map)
        let cx = width / 2, cy = height / 2

        var values: [Float] = []
        for y in max(0, cy - patchRadius)...min(height - 1, cy + patchRadius) {
            let row = (base + y * bytesPerRow).assumingMemoryBound(to: Float32.self)
            for x in max(0, cx - patchRadius)...min(width - 1, cx + patchRadius) {
                let v = row[x]
                if v.isFinite && v > 0 { values.append(v) }  // skip holes
            }
        }
        // Need at least half the square to be valid to trust the reading.
        let patchSize = (2 * patchRadius + 1) * (2 * patchRadius + 1)
        guard values.count >= patchSize / 2 else { return nil }
        values.sort()
        return values[values.count / 2]
    }

    /// Turns the depth map into a gray picture: close = white, far = black,
    /// holes (no reading) = black.
    static func grayImage(of map: CVPixelBuffer) -> CGImage? {
        CVPixelBufferLockBaseAddress(map, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(map, .readOnly) }

        guard let base = CVPixelBufferGetBaseAddress(map) else { return nil }
        let width = CVPixelBufferGetWidth(map)
        let height = CVPixelBufferGetHeight(map)
        let bytesPerRow = CVPixelBufferGetBytesPerRow(map)
        let near = nearestShown, range = farthestShown - nearestShown

        var pixels = [UInt8](repeating: 0, count: width * height)
        pixels.withUnsafeMutableBufferPointer { out in
            for y in 0..<height {
                let row = (base + y * bytesPerRow).assumingMemoryBound(to: Float32.self)
                for x in 0..<width {
                    let v = row[x]
                    guard v.isFinite && v > 0 else { continue }  // hole: stays black
                    let t = 1 - min(max((v - near) / range, 0), 1)  // 1 = near, 0 = far
                    out[y * width + x] = UInt8(t * 255)
                }
            }
        }

        guard let provider = CGDataProvider(data: Data(pixels) as CFData) else { return nil }
        return CGImage(width: width, height: height,
                       bitsPerComponent: 8, bitsPerPixel: 8, bytesPerRow: width,
                       space: CGColorSpaceCreateDeviceGray(),
                       bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.none.rawValue),
                       provider: provider, decode: nil,
                       shouldInterpolate: false, intent: .defaultIntent)
    }
}
