//
//  ContentView.swift
//  BarBot
//
//  The app's main screen: tabs along the bottom for each tool.
//

import SwiftUI

struct ContentView: View {
    var body: some View {
        TabView {
            Tab("Scan", systemImage: "cube.transparent") {
                ScanView()
            }
            Tab("Depth Check", systemImage: "ruler") {
                DepthCheckView()
            }
        }
    }
}

#Preview {
    ContentView()
}
