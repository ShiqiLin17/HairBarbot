//
//  HaircutFlowView.swift
//  HairBarbot
//
//  Starting a haircut: choose the person, then the style, then the ready screen.
//  Styles and the cutting screen are PLACEHOLDERS for now.
//

import SwiftUI

// MARK: - 3a. Who's getting the haircut?

struct ChoosePersonScreen: View {
    @Binding var path: [Route]
    let onScan: () -> Void
    @Environment(HeadStore.self) private var heads

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Choose the person whose head was scanned.")
                    .font(.body)
                    .foregroundStyle(Color.brand.muted)
                if heads.heads.isEmpty {
                    VStack(alignment: .leading, spacing: 14) {
                        IconRow(systemImage: "viewfinder",
                                title: "No one scanned yet",
                                detail: "HairBarbot needs a 3D scan of the head before it can cut.")
                        Button("Scan a Head", action: onScan)
                            .buttonStyle(.brandPrimary)
                    }
                    .brandCard(padding: 20)
                } else {
                    VStack(spacing: 0) {
                        ForEach(heads.heads) { head in
                            Button {
                                path.append(.chooseStyle(person: head.name))
                            } label: {
                                PersonRow(head: head)
                            }
                            .buttonStyle(.plain)
                            if head.id != heads.heads.last?.id {
                                Divider().overlay(Color.brand.line)
                            }
                        }
                    }
                    .brandCard(padding: 0)
                }
            }
            .padding(16)
        }
        .brandBackground()
        .navigationTitle("Who's getting the haircut?")
        .navigationBarTitleDisplayMode(.inline)
    }
}

// MARK: - 3b. Choose a style (placeholder)

/// Placeholder styles. Real styles (length per region, fades) come later.
private struct StyleOption: Identifiable {
    let name: String
    let detail: String
    let systemImage: String
    let available: Bool
    var id: String { name }
}

struct ChooseStyleScreen: View {
    let person: String
    @Binding var path: [Route]
    @State private var selected: String?

    private let options = [
        StyleOption(name: "Placeholder style", detail: "For trying the screens", systemImage: "square.dashed", available: true),
        StyleOption(name: "Even trim", detail: "Same length all over", systemImage: "circle.grid.cross", available: false),
        StyleOption(name: "Fade", detail: "Short sides, longer top", systemImage: "gradient", available: false),
        StyleOption(name: "Custom", detail: "Pick a length for each area", systemImage: "slider.horizontal.3", available: false),
    ]

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    Label("Styles are coming soon. Pick the placeholder to continue.", systemImage: "info.circle")
                        .font(.subheadline)
                        .foregroundStyle(Color.brand.ink)
                        .brandCard()

                    LazyVGrid(columns: [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)],
                              spacing: 12) {
                        ForEach(options) { option in
                            styleCard(option)
                        }
                    }
                }
                .padding(16)
            }
            Button("Continue") {
                if let selected { path.append(.ready(person: person, style: selected)) }
            }
            .buttonStyle(.brandPrimary)
            .disabled(selected == nil)
            .padding(16)
        }
        .brandBackground()
        .navigationTitle("Style for \(person)")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func styleCard(_ option: StyleOption) -> some View {
        let isSelected = selected == option.name
        return Button {
            selected = option.name
        } label: {
            VStack(alignment: .leading, spacing: 10) {
                Image(systemName: option.systemImage)
                    .font(.title)
                    .foregroundStyle(Color.brand.primary)
                Text(option.name)
                    .font(.headline)
                    .foregroundStyle(Color.brand.ink)
                Text(option.available ? option.detail : "Coming soon")
                    .font(.subheadline)
                    .foregroundStyle(Color.brand.muted)
            }
            .frame(maxWidth: .infinity, minHeight: 120, alignment: .topLeading)
            .padding(14)
            .background(Color.brand.surface, in: RoundedRectangle(cornerRadius: BrandMetrics.cardRadius))
            .overlay(RoundedRectangle(cornerRadius: BrandMetrics.cardRadius)
                .strokeBorder(isSelected ? Color.brand.primary : Color.brand.line,
                              lineWidth: isSelected ? 2.5 : BrandMetrics.borderWidth))
            .opacity(option.available ? 1 : 0.45)
        }
        .buttonStyle(.plain)
        .disabled(!option.available)
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }
}

// MARK: - 3c. Ready (placeholder)

struct ReadyScreen: View {
    let person: String
    let style: String
    @Binding var path: [Route]

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    VStack(alignment: .leading, spacing: 14) {
                        IconRow(systemImage: "person.crop.circle", title: person, detail: "Head scan saved")
                        Divider().overlay(Color.brand.line)
                        IconRow(systemImage: "scissors", title: style, detail: "Style")
                    }
                    .brandCard(padding: 20)

                    CutterCard()

                    VStack(alignment: .leading, spacing: 8) {
                        IconRow(systemImage: "hammer",
                                title: "Cutting screen coming soon",
                                detail: "Next: line up the head with the camera, follow the cutter live, and keep a STOP button on screen the whole time.")
                    }
                    .brandCard(padding: 20)
                }
                .padding(16)
            }
            Button("Back to Home") { path.removeAll() }
                .buttonStyle(.brandPrimary)
                .padding(16)
        }
        .brandBackground()
        .navigationTitle("Ready")
        .navigationBarTitleDisplayMode(.inline)
    }
}
