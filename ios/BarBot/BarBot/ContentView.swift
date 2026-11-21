//
//  ContentView.swift
//  BarBot
//
//  The app's main screen: tabs along the bottom for each tool.
//

import SwiftUI

struct ContentView: View {
    /// Saved heads, shared by every tab (made in Scan, used by tracking).
    @State private var heads = HeadStore()

    var body: some View {
        TabView {
            Tab("Scan", systemImage: "cube.transparent") {
                ScanView()
            }
            Tab("Depth Check", systemImage: "ruler") {
                DepthCheckView()
            }
        }
        .environment(heads)
    }
}

#Preview {
    ContentView()
}
