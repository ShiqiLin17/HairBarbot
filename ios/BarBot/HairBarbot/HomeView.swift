//
//  HomeView.swift
//  HairBarbot
//
//  The main menu: cutter connection, Start Haircut, Scan a New Head, and the
//  people whose heads are saved.
//

import SwiftUI

/// Screens pushed from Home.
enum Route: Hashable {
    case choosePerson
    case chooseStyle(person: String)
    case ready(person: String, style: String)
}

/// Opens the scan flow, optionally for someone already saved (rescan).
struct ScanRequest: Identifiable {
    let id = UUID()
    var name = ""
}

struct HomeView: View {
    @Environment(HeadStore.self) private var heads
    @State private var path: [Route] = []
    @State private var scanRequest: ScanRequest?
    @State private var viewingPerson: SavedHead?
    /// Set by Rescan in the person sheet; the scan opens once the sheet has closed.
    @State private var pendingRescan: String?

    var body: some View {
        NavigationStack(path: $path) {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    hero
                    CutterCard()
                    Button {
                        path = [.choosePerson]
                    } label: {
                        Label("Start Haircut", systemImage: "scissors")
                    }
                    .buttonStyle(.brandPrimary)
                    Button {
                        scanRequest = ScanRequest()
                    } label: {
                        Label("Scan a New Head", systemImage: "viewfinder")
                    }
                    .buttonStyle(.brandSecondary)
                    people
                }
                .padding(16)
            }
            .brandBackground()
            .toolbar(.hidden, for: .navigationBar)
            .navigationDestination(for: Route.self) { route in
                switch route {
                case .choosePerson:
                    ChoosePersonScreen(path: $path, onScan: { scanRequest = ScanRequest() })
                case .chooseStyle(let person):
                    ChooseStyleScreen(person: person, path: $path)
                case .ready(let person, let style):
                    ReadyScreen(person: person, style: style, path: $path)
                }
            }
        }
        .tint(Color.brand.primary)
        .fullScreenCover(item: $scanRequest) { request in
            ScanFlowView(suggestedName: request.name) { startHaircutFor in
                scanRequest = nil
                if let name = startHaircutFor {
                    path = [.chooseStyle(person: name)]
                }
            }
        }
        .sheet(item: $viewingPerson, onDismiss: {
            if let name = pendingRescan {
                pendingRescan = nil
                scanRequest = ScanRequest(name: name)
            }
        }) { head in
            PersonSheet(head: head, onRescan: {
                pendingRescan = head.name
                viewingPerson = nil
            })
        }
    }

    /// Navy header with the app icon art.
    private var hero: some View {
        HStack(spacing: 16) {
            Image("BrandIcon")
                .resizable()
                .scaledToFit()
                .frame(width: 64, height: 64)
                .clipShape(RoundedRectangle(cornerRadius: 14))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text("HairBarbot")
                    .font(.largeTitle.bold())
                Text("Scan once, then cut.")
                    .font(.subheadline)
                    .opacity(0.8)
            }
            .foregroundStyle(Color.brand.warmWhite)
            Spacer(minLength: 0)
        }
        .padding(20)
        .background(Color.brand.navy, in: RoundedRectangle(cornerRadius: BrandMetrics.cardRadius))
    }

    private var people: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("People")
                .font(.title3.bold())
                .foregroundStyle(Color.brand.ink)
                .padding(.top, 8)
            if heads.heads.isEmpty {
                Text("No one scanned yet. Scan a head to get started.")
                    .font(.body)
                    .foregroundStyle(Color.brand.muted)
                    .brandCard()
            } else {
                VStack(spacing: 0) {
                    ForEach(heads.heads) { head in
                        Button {
                            viewingPerson = head
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
    }
}

/// A saved person: name and when they were scanned.
struct PersonRow: View {
    let head: SavedHead

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: "person.crop.circle")
                .font(.title2)
                .foregroundStyle(Color.brand.primary)
            VStack(alignment: .leading, spacing: 2) {
                Text(head.name)
                    .font(.headline)
                    .foregroundStyle(Color.brand.ink)
                Text("Scanned \(head.created.formatted(date: .abbreviated, time: .omitted))")
                    .font(.subheadline)
                    .foregroundStyle(Color.brand.muted)
            }
            Spacer()
            Image(systemName: "chevron.right")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(Color.brand.muted)
        }
        .padding(16)
        .contentShape(Rectangle())
    }
}

/// A saved person's head in 3D, with Rescan and Delete.
private struct PersonSheet: View {
    let head: SavedHead
    let onRescan: () -> Void
    @Environment(HeadStore.self) private var heads
    @Environment(\.dismiss) private var dismiss
    @State private var mesh: HeadMesh?
    @State private var loadFailed = false
    @State private var confirmingDelete = false

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text(head.name)
                        .font(.title2.bold())
                        .foregroundStyle(Color.brand.ink)
                    Text("Scanned \(head.created.formatted(date: .long, time: .shortened))")
                        .font(.subheadline)
                        .foregroundStyle(Color.brand.muted)
                }
                Spacer()
                Button("Done") { dismiss() }
                    .font(.headline)
                    .foregroundStyle(Color.brand.primary)
            }

            ZStack {
                RoundedRectangle(cornerRadius: BrandMetrics.cardRadius)
                    .fill(Color.brand.surface2)
                if let mesh {
                    HeadMeshSceneView(mesh: mesh,
                                      color: UIColor(Color.brand.warmWhite),
                                      background: UIColor(Color.brand.surface2))
                        .clipShape(RoundedRectangle(cornerRadius: BrandMetrics.cardRadius))
                } else if loadFailed {
                    Label("This head couldn't be shown.", systemImage: "exclamationmark.circle")
                        .foregroundStyle(Color.brand.ink)
                } else {
                    ProgressView()
                }
            }
            .frame(maxHeight: .infinity)

            Button("Rescan", action: onRescan)
                .buttonStyle(.brandPrimary)
            // Plain text, not red: red is reserved for safety (design/style-guide.md).
            Button("Delete \(head.name)") { confirmingDelete = true }
                .font(.headline)
                .foregroundStyle(Color.brand.primary)
                .frame(maxWidth: .infinity, minHeight: 44)
        }
        .padding(20)
        .brandBackground()
        .presentationDetents([.large])
        .task {
            let head = head
            do {
                mesh = try await Task.detached(priority: .userInitiated) { try HeadMesh.build(head) }.value
            } catch {
                loadFailed = true
            }
        }
        .confirmationDialog("Delete \(head.name)'s head?", isPresented: $confirmingDelete,
                            titleVisibility: .visible) {
            Button("Delete") {
                heads.deletePerson(head)
                dismiss()
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("You'll need to scan again before cutting \(head.name)'s hair.")
        }
    }
}
