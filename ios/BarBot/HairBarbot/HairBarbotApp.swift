//
//  HairBarbotApp.swift
//  HairBarbot
//
//  The user-facing HairBarbot app. (BarBot, in ../BarBot, is the developer test app.)
//  Look and feel: design/README.md and design/style-guide.md.
//

import SwiftUI

@main
struct HairBarbotApp: App {
    /// Saved heads (one per person), shared by every screen.
    @State private var heads = HeadStore()
    @State private var cutter = CutterConnection()

    var body: some Scene {
        WindowGroup {
            HomeView()
                .environment(heads)
                .environment(cutter)
        }
    }
}
