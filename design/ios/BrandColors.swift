// GENERATED from design/tokens.json by design/build_tokens.py. Do not edit by hand.
// Use: Color.brand.primary, Color.brand.stop, Color.brand.fadeRamp[0] ...

import SwiftUI
import UIKit

private func dynamic(_ light: UIColor, _ dark: UIColor) -> Color {
    Color(UIColor { $0.userInterfaceStyle == .dark ? dark : light })
}

struct BrandColors {
    /// Main buttons, links, selected states, progress
    let primary = dynamic(UIColor(red: 0.1216, green: 0.3725, blue: 0.8392, alpha: 1), UIColor(red: 0.3098, green: 0.5412, blue: 0.9412, alpha: 1))
    /// Pressed or active state of primary
    let primaryPressed = dynamic(UIColor(red: 0.0902, green: 0.2824, blue: 0.6902, alpha: 1), UIColor(red: 0.4980, green: 0.6627, blue: 0.9608, alpha: 1))
    /// Text and icons on primary
    let onPrimary = dynamic(UIColor(red: 1.0000, green: 1.0000, blue: 1.0000, alpha: 1), UIColor(red: 0.0392, green: 0.0549, blue: 0.0784, alpha: 1))
    /// Hero headers, onboarding backgrounds
    let navy = dynamic(UIColor(red: 0.0431, green: 0.1216, blue: 0.2275, alpha: 1), UIColor(red: 0.0431, green: 0.1216, blue: 0.2275, alpha: 1))
    /// Occasional warm surface (onboarding, success cards); light mode only
    let warmWhite = dynamic(UIColor(red: 0.9686, green: 0.9569, blue: 0.9333, alpha: 1), UIColor(red: 0.9686, green: 0.9569, blue: 0.9333, alpha: 1))
    /// Screen background
    let bg = dynamic(UIColor(red: 0.9569, green: 0.9647, blue: 0.9765, alpha: 1), UIColor(red: 0.0392, green: 0.0549, blue: 0.0784, alpha: 1))
    /// Cards, sheets
    let surface = dynamic(UIColor(red: 1.0000, green: 1.0000, blue: 1.0000, alpha: 1), UIColor(red: 0.0706, green: 0.0941, blue: 0.1294, alpha: 1))
    /// Inset areas, segmented controls
    let surface2 = dynamic(UIColor(red: 0.9333, green: 0.9451, blue: 0.9608, alpha: 1), UIColor(red: 0.1020, green: 0.1333, blue: 0.1765, alpha: 1))
    /// Main text
    let ink = dynamic(UIColor(red: 0.0549, green: 0.0863, blue: 0.1255, alpha: 1), UIColor(red: 0.9137, green: 0.9333, blue: 0.9569, alpha: 1))
    /// Secondary text, captions
    let muted = dynamic(UIColor(red: 0.3569, green: 0.4000, blue: 0.4510, alpha: 1), UIColor(red: 0.5490, green: 0.6000, blue: 0.6588, alpha: 1))
    /// Dividers, card borders
    let line = dynamic(UIColor(red: 0.8627, green: 0.8863, blue: 0.9098, alpha: 1), UIColor(red: 0.1490, green: 0.1882, blue: 0.2510, alpha: 1))
    /// SAFETY ONLY: blade off, emergency stop, error, the STOP button
    let stop = dynamic(UIColor(red: 0.8510, green: 0.1765, blue: 0.1255, alpha: 1), UIColor(red: 1.0000, green: 0.2706, blue: 0.2275, alpha: 1))
    /// Text on stop (white fails contrast on dark-mode stop)
    let onStop = dynamic(UIColor(red: 1.0000, green: 1.0000, blue: 1.0000, alpha: 1), UIColor(red: 0.1020, green: 0.0196, blue: 0.0118, alpha: 1))
    /// SAFETY ONLY: wait or adjust (rollers moving, move slower, low battery)
    let warn = dynamic(UIColor(red: 0.7098, green: 0.2784, blue: 0.0314, alpha: 1), UIColor(red: 0.9608, green: 0.6471, blue: 0.1412, alpha: 1))
    /// SAFETY ONLY: ready to cut, connected. Not for 'area done' fills
    let ok = dynamic(UIColor(red: 0.1176, green: 0.4980, blue: 0.2980, alpha: 1), UIColor(red: 0.2392, green: 0.8392, blue: 0.5490, alpha: 1))
    /// Hair-length maps and legends only. Index 0 = longest hair, last = shortest. Same in light and dark mode. Always pair with a numeric length label.
    let fadeRamp: [Color] = [Color(UIColor(red: 0.0431, green: 0.1216, blue: 0.2275, alpha: 1)), Color(UIColor(red: 0.0941, green: 0.2353, blue: 0.4510, alpha: 1)), Color(UIColor(red: 0.1765, green: 0.3882, blue: 0.7098, alpha: 1)), Color(UIColor(red: 0.4314, green: 0.6078, blue: 0.8902, alpha: 1)), Color(UIColor(red: 0.7098, green: 0.8039, blue: 0.9765, alpha: 1))]
}

enum BrandMetrics {
    static let cardRadius: CGFloat = 14
    static let buttonRadius: CGFloat = 16
    static let chipRadius: CGFloat = 999
    static let stopButtonMinHeight: CGFloat = 56
    static let borderWidth: CGFloat = 1
}

extension Color {
    static let brand = BrandColors()
}
