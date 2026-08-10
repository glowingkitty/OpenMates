// Maps location sharing for the native Apple composer.
// Mirrors the web map overlay, explicit selection flow, and location embed data.
// MapKit remains the platform map provider while OpenMates controls all chrome.
// Selected locations become canonical maps embed atoms, never plaintext coordinates.
// Search results and privacy precision remain explicit user decisions.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/enter_message/MapsView.svelte
//          frontend/packages/ui/src/components/embeds/maps/MapsLocationEmbedPreview.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import MapKit
import SwiftUI

struct ComposerLocationSelection: Sendable {
    let latitude: Double
    let longitude: Double
    let name: String
    let address: String?
    let placeType: String?
    let isPrecise: Bool

    func makePendingEmbed() -> ComposerPendingEmbed {
        let embedID = "location-\(UUID().uuidString.lowercased())"
        var data: [String: AnyCodable] = [
            "type": AnyCodable("location"),
            "name": AnyCodable(name),
            "precise_lat": AnyCodable(latitude),
            "precise_lon": AnyCodable(longitude),
            "location_type": AnyCodable(isPrecise ? "precise" : "area"),
            "status": AnyCodable("finished"),
        ]
        if let address, !address.isEmpty { data["address"] = AnyCodable(address) }
        if let placeType, !placeType.isEmpty { data["place_type"] = AnyCodable(placeType) }

        let record = EmbedRecord(
            id: embedID,
            type: "maps",
            status: .finished,
            data: .raw(data),
            parentEmbedId: nil,
            appId: "maps",
            skillId: "location",
            embedIds: nil,
            createdAt: String(Int(Date().timeIntervalSince1970))
        )
        return ComposerPendingEmbed(
            id: embedID,
            type: "maps",
            referenceType: "location",
            status: "finished",
            content: nil,
            textPreview: name,
            record: record,
            localData: nil,
            filename: "location",
            size: 1,
            piiMappings: []
        )
    }
}

struct ComposerLocationOverlay: View {
    @Binding var isFullscreen: Bool
    let onShare: (ComposerLocationSelection) -> Void
    let onCancel: () -> Void

    @State private var position: MapCameraPosition = .automatic
    @State private var selectedLocation: CLLocationCoordinate2D?
    @State private var selectedName = ""
    @State private var selectedAddress: String?
    @State private var selectedPlaceType: String?
    @State private var searchText = ""
    @State private var searchResults: [MKMapItem] = []
    @State private var isPrecise = true

    var body: some View {
        ZStack(alignment: .top) {
            map
            preciseToggle
            fullscreenButton
            selectionIndicator
            bottomBar
            searchResultsPanel
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: 24))
        .clipped()
        .accessibilityIdentifier("location-overlay")
    }

    private var map: some View {
        MapReader { proxy in
            Map(position: $position) {
                if let selectedLocation {
                    Marker(displayName, coordinate: selectedLocation)
                        .tint(Color.error)
                }
                ForEach(searchResults, id: \.self) { item in
                    if let coordinate = item.placemark.location?.coordinate {
                        Marker(item.name ?? AppStrings.selectedLocation, coordinate: coordinate)
                    }
                }
            }
            .mapStyle(.standard(elevation: .realistic))
            .onTapGesture { point in
                guard let coordinate = proxy.convert(point, from: .local) else { return }
                selectedLocation = coordinate
                selectedName = AppStrings.selectedLocation
                selectedAddress = nil
                selectedPlaceType = nil
                searchResults = []
            }
        }
        .padding(.bottom, 53)
        .accessibilityIdentifier("location-map")
    }

    private var preciseToggle: some View {
        HStack(spacing: .spacing3) {
            Text(AppStrings.preciseLocation)
                .font(.omXs.weight(.medium))
                .foregroundStyle(Color.fontPrimary)
            OMToggle(isOn: $isPrecise)
        }
        .padding(.horizontal, .spacing4)
        .padding(.vertical, .spacing2)
        .background(Color.grey0.opacity(0.94))
        .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
        .padding(.top, .spacing5)
        .accessibilityIdentifier("location-precise-toggle")
    }

    private var fullscreenButton: some View {
        Button { isFullscreen.toggle() } label: {
            Icon(isFullscreen ? "minimize" : "fullscreen", size: 18)
                .foregroundStyle(Color.fontPrimary)
                .frame(width: 32, height: 32)
                .background(Color.grey0.opacity(0.9))
                .clipShape(RoundedRectangle(cornerRadius: .radius3))
        }
        .buttonStyle(.plain)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
        .padding(.top, 10)
        .padding(.trailing, 12)
        .accessibilityLabel(isFullscreen ? AppStrings.exitFullscreen : AppStrings.enterFullscreen)
        .accessibilityIdentifier("location-fullscreen-button")
    }

    @ViewBuilder
    private var selectionIndicator: some View {
        if let selectedLocation {
            VStack(spacing: .spacing3) {
                Text(displayName)
                    .font(.omSmall.weight(.semibold))
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(2)
                    .multilineTextAlignment(.center)
                Button {
                    onShare(ComposerLocationSelection(
                        latitude: selectedLocation.latitude,
                        longitude: selectedLocation.longitude,
                        name: displayName,
                        address: selectedAddress,
                        placeType: selectedPlaceType,
                        isPrecise: isPrecise
                    ))
                } label: {
                    Text(AppStrings.locationSelect)
                        .font(.omSmall.weight(.semibold))
                        .foregroundStyle(Color.fontButton)
                        .padding(.horizontal, .spacing8)
                        .frame(height: 40)
                        .background(Color.buttonPrimary)
                        .clipShape(RoundedRectangle(cornerRadius: .radius8))
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("location-select-button")
            }
            .padding(.spacing4)
            .background(Color.grey0.opacity(0.94))
            .clipShape(RoundedRectangle(cornerRadius: .radius8))
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
            .padding(.horizontal, .spacing8)
            .padding(.bottom, 65)
        }
    }

    private var bottomBar: some View {
        HStack(spacing: .spacing4) {
            Button(action: onCancel) {
                Icon("close", size: 20).foregroundStyle(Color.fontSecondary)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(AppStrings.close)

            HStack(spacing: .spacing3) {
                Icon("search", size: 18).foregroundStyle(Color.fontTertiary)
                TextField(AppStrings.search, text: $searchText)
                    .textFieldStyle(.plain)
                    .font(.omSmall)
                    .onSubmit(performSearch)
                    .accessibilityIdentifier("location-search-input")
            }
            .padding(.horizontal, .spacing5)
            .frame(height: 40)
            .background(Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radiusFull))

            Button {
                position = .userLocation(followsHeading: false, fallback: .automatic)
            } label: {
                Icon("current_location", size: 20).foregroundStyle(Color.buttonPrimary)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(AppStrings.getLocation)
            .accessibilityIdentifier("location-current-button")
        }
        .padding(.horizontal, .spacing5)
        .frame(height: 53)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
        .background(alignment: .bottom) {
            Color.grey0.frame(height: 53)
        }
    }

    @ViewBuilder
    private var searchResultsPanel: some View {
        if !searchResults.isEmpty {
            ScrollView {
                LazyVStack(spacing: .spacing2) {
                    ForEach(Array(searchResults.enumerated()), id: \.element) { index, item in
                        Button { selectSearchResult(item) } label: {
                            HStack(spacing: .spacing4) {
                                Icon("maps", size: 18).foregroundStyle(Color.buttonPrimary)
                                VStack(alignment: .leading, spacing: .spacing1) {
                                    Text(item.name ?? AppStrings.selectedLocation)
                                        .font(.omSmall.weight(.semibold))
                                        .foregroundStyle(Color.fontPrimary)
                                    if let address = item.placemark.title {
                                        Text(address)
                                            .font(.omXs)
                                            .foregroundStyle(Color.fontSecondary)
                                            .lineLimit(2)
                                    }
                                }
                                Spacer(minLength: 0)
                            }
                            .padding(.spacing4)
                            .background(Color.grey0)
                            .clipShape(RoundedRectangle(cornerRadius: .radius8))
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("location-search-result-\(index)")
                    }
                }
                .padding(.spacing3)
            }
            .frame(maxWidth: 320, maxHeight: 250)
            .background(Color.grey10)
            .clipShape(RoundedRectangle(cornerRadius: .radius8))
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
            .padding(.leading, .spacing5)
            .padding(.bottom, 58)
            .accessibilityIdentifier("location-search-results")
        }
    }

    private var displayName: String {
        selectedName.isEmpty ? AppStrings.selectedLocation : selectedName
    }

    private func performSearch() {
        guard !searchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        let request = MKLocalSearch.Request()
        request.naturalLanguageQuery = searchText
        MKLocalSearch(request: request).start { response, _ in
            searchResults = response?.mapItems ?? []
        }
    }

    private func selectSearchResult(_ item: MKMapItem) {
        guard let coordinate = item.placemark.location?.coordinate else { return }
        selectedLocation = coordinate
        selectedName = item.name ?? AppStrings.selectedLocation
        selectedAddress = item.placemark.title
        selectedPlaceType = item.pointOfInterestCategory?.rawValue
        searchResults = []
        position = .camera(MapCamera(centerCoordinate: coordinate, distance: 5_000))
    }
}

struct MapsShareView: View {
    @Binding var isFullscreen: Bool
    let onShare: (ComposerLocationSelection) -> Void
    let onCancel: () -> Void

    var body: some View {
        ComposerLocationOverlay(
            isFullscreen: $isFullscreen,
            onShare: onShare,
            onCancel: onCancel
        )
    }
}
