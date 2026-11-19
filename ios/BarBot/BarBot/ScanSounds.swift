//
//  ScanSounds.swift
//  BarBot
//
//  Audio feedback while scanning, so the person holding the phone (who can't
//  see the screen) knows how tracking is going:
//    - good tracking: a soft high tick twice a second
//    - poor or lost tracking: a low beep about three times a second
//
//  The tones are generated in code (short sine waves) and play even when the
//  phone's silent switch is on.
//

import AVFoundation
import StandardCyborgUI

final class ScanSounds {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let format = AVAudioFormat(standardFormatWithSampleRate: 44_100, channels: 1)!
    private lazy var tick = Self.tone(frequency: 1_800, duration: 0.03, volume: 0.25, format: format)
    private lazy var warning = Self.tone(frequency: 440, duration: 0.15, volume: 0.6, format: format)
    private var lastSound = Date.distantPast
    private var isRunning = false

    /// When true, no sounds play (the scan screen's speaker button).
    var isMuted = false

    init() {
        engine.attach(player)
        engine.connect(player, to: engine.mainMixerNode, format: format)
    }

    func start() {
        guard !isRunning else { return }
        let session = AVAudioSession.sharedInstance()
        // .playback ignores the silent switch; mixWithOthers leaves music etc. alone
        try? session.setCategory(.playback, options: [.mixWithOthers])
        try? session.setActive(true)
        do {
            try engine.start()
            player.play()
            isRunning = true
            lastSound = .distantPast
        } catch {
            print("ScanSounds: couldn't start audio: \(error)")
        }
    }

    func stop() {
        guard isRunning else { return }
        player.stop()
        engine.stop()
        isRunning = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    /// Called for every frame (~30 per second); plays a sound when one is due.
    func update(_ quality: ScanTrackingQuality) {
        guard isRunning, !isMuted else { return }
        let interval: TimeInterval = quality == .good ? 0.5 : 0.3
        let now = Date()
        guard now.timeIntervalSince(lastSound) >= interval else { return }
        lastSound = now
        player.scheduleBuffer(quality == .good ? tick : warning)
    }

    /// A short sine tone with 5 ms fade in/out (so it doesn't click).
    private static func tone(frequency: Double, duration: Double, volume: Float,
                             format: AVAudioFormat) -> AVAudioPCMBuffer {
        let sampleRate = format.sampleRate
        let frameCount = AVAudioFrameCount(duration * sampleRate)
        let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCount)!
        buffer.frameLength = frameCount
        let samples = buffer.floatChannelData![0]
        let fadeFrames = Int(0.005 * sampleRate)
        for i in 0..<Int(frameCount) {
            let fadeIn = min(1, Float(i) / Float(fadeFrames))
            let fadeOut = min(1, Float(Int(frameCount) - i) / Float(fadeFrames))
            let wave = Float(sin(2 * Double.pi * frequency * Double(i) / sampleRate))
            samples[i] = wave * volume * min(fadeIn, fadeOut)
        }
        return buffer
    }
}
