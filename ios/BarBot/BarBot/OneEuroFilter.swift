//
//  OneEuroFilter.swift
//  BarBot
//
//  The "One Euro" smoothing filter (Casiez, Roussel & Vogel, CHI 2012), for a pose
//  (position + rotation).
//
//  It smooths heavily when the head is still (tiny wobbles disappear) and lightly when it
//  moves fast (so the pose keeps up instead of lagging). Each update it:
//    1. measures how fast things are moving (itself smoothed a little),
//    2. picks a cutoff: minCutoff when still, rising by beta × speed when moving,
//    3. moves the smoothed value part of the way toward the new one (more for a higher cutoff).
//
//  Two knobs per part: minCutoff (Hz; lower = smoother when still) and beta (how quickly
//  the smoothing lets go as speed rises).
//

import Foundation
import simd

struct OneEuroPoseFilter {
    // Position: speed in meters per second
    var positionMinCutoff: Float = 1.0
    var positionBeta: Float = 40
    // Rotation: speed in radians per second
    var rotationMinCutoff: Float = 1.0
    var rotationBeta: Float = 4
    /// Cutoff (Hz) for smoothing the speed estimate itself.
    var speedCutoff: Float = 1.0

    private var lastTime: TimeInterval?
    private var position = SIMD3<Float>.zero
    private var rotation = simd_quatf(ix: 0, iy: 0, iz: 0, r: 1)
    private var positionSpeed: Float = 0
    private var rotationSpeed: Float = 0

    /// Starts over (e.g. after tracking was lost), so the next pose is taken as is.
    mutating func reset() { lastTime = nil }

    /// Smooths `pose` (a rigid 4×4 transform) seen at `time` (seconds). Returns the smoothed pose.
    mutating func update(_ pose: simd_float4x4, time: TimeInterval) -> simd_float4x4 {
        let newPosition = SIMD3(pose.columns.3.x, pose.columns.3.y, pose.columns.3.z)
        var newRotation = simd_quatf(simd_float3x3(SIMD3(pose.columns.0.x, pose.columns.0.y, pose.columns.0.z),
                                                   SIMD3(pose.columns.1.x, pose.columns.1.y, pose.columns.1.z),
                                                   SIMD3(pose.columns.2.x, pose.columns.2.y, pose.columns.2.z)))
        guard let lastTime, time > lastTime else {
            self.lastTime = time
            position = newPosition
            rotation = newRotation
            positionSpeed = 0
            rotationSpeed = 0
            return pose
        }
        let dt = Float(time - lastTime)
        self.lastTime = time

        // Big jump (e.g. a different person, or tracking came back elsewhere): don't smooth across it
        if simd_distance(newPosition, position) > 0.05 {
            position = newPosition
            rotation = newRotation
            positionSpeed = 0
            rotationSpeed = 0
            return pose
        }

        // Position
        let rawPositionSpeed = simd_distance(newPosition, position) / dt
        positionSpeed += Self.alpha(cutoff: speedCutoff, dt: dt) * (rawPositionSpeed - positionSpeed)
        let positionCutoff = positionMinCutoff + positionBeta * positionSpeed
        position += Self.alpha(cutoff: positionCutoff, dt: dt) * (newPosition - position)

        // Rotation (q and -q are the same turn: pick the one closest to the current one)
        if simd_dot(newRotation.vector, rotation.vector) < 0 { newRotation = simd_quatf(vector: -newRotation.vector) }
        let rawRotationSpeed = (rotation.inverse * newRotation).angle / dt
        rotationSpeed += Self.alpha(cutoff: speedCutoff, dt: dt) * (rawRotationSpeed - rotationSpeed)
        let rotationCutoff = rotationMinCutoff + rotationBeta * rotationSpeed
        rotation = simd_slerp(rotation, newRotation, Self.alpha(cutoff: rotationCutoff, dt: dt)).normalized

        var result = simd_float4x4(rotation)
        result.columns.3 = SIMD4(position, 1)
        return result
    }

    /// How far to move toward the new value for a given cutoff (Hz) and time step (s).
    private static func alpha(cutoff: Float, dt: Float) -> Float {
        let tau = 1 / (2 * Float.pi * cutoff)
        return 1 / (1 + tau / dt)
    }
}
