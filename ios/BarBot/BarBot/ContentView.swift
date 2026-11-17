//
//  ContentView.swift
//  BarBot
//
//  The depth-check screen: a gray depth picture with a target in the middle,
//  the distance to that target in big numbers, and a Hold button that
//  freezes the reading so you can turn the phone around and read it.
//

import SwiftUI
import UIKit

struct ContentView: View {
    @State private var camera = DepthCamera()
    @Environment(\.openURL) private var openURL

    var body: some View {
        VStack(spacing: 16) {
            if camera.permissionDenied {
                permissionMessage
            } else {
                depthPicture
                distanceText
                holdButton
                Text(camera.status)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
        }
        .padding()
        .onAppear {
            camera.start()
            // Keep the screen on while measuring (the phone faces the wall).
            UIApplication.shared.isIdleTimerDisabled = true
        }
        .onDisappear {
            camera.stop()
            UIApplication.shared.isIdleTimerDisabled = false
        }
    }

    /// The gray depth picture, with a red target marking the measured spot.
    private var depthPicture: some View {
        ZStack {
            Rectangle().fill(.black)
            if let image = camera.depthImage {
                // The camera's picture comes in sideways and mirrored;
                // .leftMirrored turns it upright for a phone held normally.
                Image(decorative: image, scale: 1, orientation: .leftMirrored)
                    .resizable()
                    .scaledToFit()
            }
            Image(systemName: "plus.circle")
                .font(.system(size: 36, weight: .light))
                .foregroundStyle(.red)
        }
        .aspectRatio(3 / 4, contentMode: .fit)
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }

    /// The distance in big numbers, e.g. "42.3 cm".
    private var distanceText: some View {
        Group {
            if let meters = camera.centerDistanceMeters {
                Text(String(format: "%.1f cm", meters * 100))
            } else {
                Text("— cm")
            }
        }
        .font(.system(size: 64, weight: .bold, design: .rounded))
        .monospacedDigit()
        .foregroundStyle(camera.isHeld ? .orange : .primary)
    }

    private var holdButton: some View {
        Button {
            camera.isHeld.toggle()
        } label: {
            Label(camera.isHeld ? "Release" : "Hold",
                  systemImage: camera.isHeld ? "play.fill" : "pause.fill")
                .font(.title2)
                .frame(maxWidth: .infinity)
        }
        .buttonStyle(.borderedProminent)
        .tint(camera.isHeld ? .orange : .blue)
    }

    /// Shown if you tapped "Don't Allow" on the camera popup.
    private var permissionMessage: some View {
        VStack(spacing: 16) {
            Image(systemName: "camera.fill")
                .font(.system(size: 48))
                .foregroundStyle(.secondary)
            Text("BarBot needs the camera to measure distance.")
                .font(.headline)
                .multilineTextAlignment(.center)
            Text("Turn it on in Settings → BarBot → Camera.")
                .foregroundStyle(.secondary)
            Button("Open Settings") {
                if let url = URL(string: UIApplication.openSettingsURLString) {
                    openURL(url)
                }
            }
            .buttonStyle(.borderedProminent)
        }
    }
}

#Preview {
    ContentView()
}
