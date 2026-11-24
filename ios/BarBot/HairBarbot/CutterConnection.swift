//
//  CutterConnection.swift
//  HairBarbot
//
//  PLACEHOLDER for the Bluetooth link to the HairBarbot cutter. The screens already
//  use this object, so the real connection (CoreBluetooth) can replace the inside
//  later without changing them. For now it never connects.
//

import Observation
import SwiftUI

@Observable
final class CutterConnection {
    /// True once the cutter is connected over Bluetooth. Always false for now.
    private(set) var isConnected = false

    /// Shows the "coming soon" sheet (set by connect()).
    var showingComingSoon = false

    /// Starts connecting to the cutter. Placeholder: only explains that it's not built yet.
    func connect() {
        showingComingSoon = true
    }
}

/// "Cutter connected / not connected" with a Connect button. Used on Home and before a cut.
struct CutterCard: View {
    @Environment(CutterConnection.self) private var cutter

    var body: some View {
        @Bindable var cutter = cutter
        HStack(spacing: 14) {
            Image(systemName: cutter.isConnected ? "checkmark.circle.fill" : "antenna.radiowaves.left.and.right")
                .font(.title2)
                // green only for "connected" (style guide: status colors are functional)
                .foregroundStyle(cutter.isConnected ? Color.brand.ok : Color.brand.muted)
                .frame(width: 32)
            VStack(alignment: .leading, spacing: 2) {
                Text("Cutter")
                    .font(.subheadline)
                    .foregroundStyle(Color.brand.muted)
                Text(cutter.isConnected ? "Connected" : "Not connected")
                    .font(.headline)
                    .foregroundStyle(Color.brand.ink)
            }
            Spacer()
            if !cutter.isConnected {
                Button("Connect") { cutter.connect() }
                    .font(.headline)
                    .foregroundStyle(Color.brand.primary)
                    .buttonStyle(.plain)
            }
        }
        .brandCard()
        .sheet(isPresented: $cutter.showingComingSoon) {
            ComingSoonSheet(systemImage: "antenna.radiowaves.left.and.right",
                            title: "Bluetooth connection is coming soon",
                            message: "Soon you'll connect the HairBarbot cutter here. Until then, you can scan heads and try the haircut screens.")
        }
    }
}

/// A small sheet for features that aren't built yet.
struct ComingSoonSheet: View {
    let systemImage: String
    let title: String
    let message: String
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 18) {
            Image(systemName: systemImage)
                .font(.system(size: 44))
                .foregroundStyle(Color.brand.primary)
                .padding(.top, 28)
            Text(title)
                .font(.title3.bold())
                .foregroundStyle(Color.brand.ink)
                .multilineTextAlignment(.center)
            Text(message)
                .font(.body)
                .foregroundStyle(Color.brand.muted)
                .multilineTextAlignment(.center)
            Spacer()
            Button("OK") { dismiss() }
                .buttonStyle(.brandPrimary)
        }
        .padding(24)
        .brandBackground()
        .presentationDetents([.medium])
    }
}
