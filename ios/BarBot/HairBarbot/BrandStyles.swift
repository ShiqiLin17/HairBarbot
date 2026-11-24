//
//  BrandStyles.swift
//  HairBarbot
//
//  Buttons and cards in the HairBarbot look (design/style-guide.md).
//  Colors come only from Color.brand (design/ios/BrandColors.swift, generated
//  from design/tokens.json) and sizes from BrandMetrics. No hex values here.
//

import SwiftUI

/// The one main action on a screen: full width, filled brand blue.
struct PrimaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline)
            .frame(maxWidth: .infinity, minHeight: 52)
            .foregroundStyle(Color.brand.onPrimary)
            .background(configuration.isPressed ? Color.brand.primaryPressed : Color.brand.primary,
                        in: RoundedRectangle(cornerRadius: BrandMetrics.buttonRadius))
            .opacity(isEnabled ? 1 : 0.4)
            .contentShape(Rectangle())
    }
}

/// Secondary actions (Redo, Scan a New Head): outlined in brand blue.
struct SecondaryButtonStyle: ButtonStyle {
    @Environment(\.isEnabled) private var isEnabled

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline)
            .frame(maxWidth: .infinity, minHeight: 52)
            .foregroundStyle(configuration.isPressed ? Color.brand.primaryPressed : Color.brand.primary)
            .background(Color.brand.surface, in: RoundedRectangle(cornerRadius: BrandMetrics.buttonRadius))
            .overlay(RoundedRectangle(cornerRadius: BrandMetrics.buttonRadius)
                .strokeBorder(Color.brand.primary, lineWidth: 1.5))
            .opacity(isEnabled ? 1 : 0.4)
            .contentShape(Rectangle())
    }
}

extension ButtonStyle where Self == PrimaryButtonStyle {
    static var brandPrimary: PrimaryButtonStyle { PrimaryButtonStyle() }
}

extension ButtonStyle where Self == SecondaryButtonStyle {
    static var brandSecondary: SecondaryButtonStyle { SecondaryButtonStyle() }
}

extension View {
    /// A card: surface color, 14 pt corners, 1 pt line border, no shadow.
    func brandCard(padding: CGFloat = 16) -> some View {
        self
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.brand.surface, in: RoundedRectangle(cornerRadius: BrandMetrics.cardRadius))
            .overlay(RoundedRectangle(cornerRadius: BrandMetrics.cardRadius)
                .strokeBorder(Color.brand.line, lineWidth: BrandMetrics.borderWidth))
    }

    /// The screen background.
    func brandBackground() -> some View {
        background(Color.brand.bg.ignoresSafeArea())
    }
}

/// A row with an SF Symbol and text, for checklists and legends.
struct IconRow<Trailing: View>: View {
    let systemImage: String
    let title: String
    var detail: String?
    @ViewBuilder var trailing: () -> Trailing

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: systemImage)
                .font(.title3)
                .foregroundStyle(Color.brand.primary)
                .frame(width: 28)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.body.weight(.semibold))
                    .foregroundStyle(Color.brand.ink)
                if let detail {
                    Text(detail)
                        .font(.subheadline)
                        .foregroundStyle(Color.brand.muted)
                }
            }
            Spacer(minLength: 0)
            trailing()
        }
    }
}

extension IconRow where Trailing == EmptyView {
    init(systemImage: String, title: String, detail: String? = nil) {
        self.init(systemImage: systemImage, title: title, detail: detail, trailing: { EmptyView() })
    }
}
