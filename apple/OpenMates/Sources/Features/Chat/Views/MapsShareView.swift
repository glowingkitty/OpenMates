// Maps location sharing — pick a location on a map to share in chat.
// Mirrors the web app's enter_message/MapsView.svelte.
// Uses MapKit for native Apple Maps integration with search and pin drop.

import SwiftUI
import MapKit

struct ComposerLocationOverlay: View {
    let onShare: (Double, Double, String) -> Void
    let onCancel: () -> Void

    @State private var position: MapCameraPosition = .automatic
    @State private var selectedLocation: CLLocationCoordinate2D?
    @State private var selectedName = ""
    @State private var searchText = ""
    @State private var searchResults: [MKMapItem] = []

    var body: some View {
        ZStack(alignment: .top) {
            MapReader { proxy in
                Map(position: $position) {
                    if let selectedLocation {
                        Marker(selectedName.isEmpty ? AppStrings.selectedLocation : selectedName, coordinate: selectedLocation)
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
                    if let coordinate = proxy.convert(point, from: .local) {
                        selectedLocation = coordinate
                        selectedName = AppStrings.selectedLocation
                    }
                }
            }

            VStack(spacing: .spacing4) {
                HStack(spacing: .spacing3) {
                    Icon("search", size: 18)
                        .foregroundStyle(Color.fontTertiary)
                    TextField(AppStrings.search, text: $searchText)
                        .textFieldStyle(.plain)
                        .font(.omSmall)
                        .onSubmit { searchPlaces() }
                    Button(action: onCancel) {
                        Icon("close", size: 18)
                            .foregroundStyle(Color.fontSecondary)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(AppStrings.cancel)
                }
                .padding(.horizontal, .spacing5)
                .frame(height: 44)
                .background(Color.grey0.opacity(0.94))
                .clipShape(RoundedRectangle(cornerRadius: .radiusFull))
                .shadow(color: .black.opacity(0.12), radius: 8, x: 0, y: 2)
                .padding(.horizontal, .spacing5)
                .padding(.top, .spacing5)

                Spacer()

                if let selectedLocation {
                    Button {
                        onShare(selectedLocation.latitude, selectedLocation.longitude, selectedName)
                    } label: {
                        HStack(spacing: .spacing3) {
                            Icon("current_location", size: 16)
                            Text(AppStrings.shareLocation)
                                .font(.omSmall.weight(.medium))
                        }
                        .foregroundStyle(Color.fontButton)
                        .padding(.horizontal, .spacing8)
                        .frame(height: 40)
                        .background(Color.buttonPrimary)
                        .clipShape(RoundedRectangle(cornerRadius: .radius8))
                    }
                    .buttonStyle(.plain)
                    .padding(.bottom, .spacing5)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.grey100)
        .clipShape(RoundedRectangle(cornerRadius: 24))
        .clipped()
    }

    private func searchPlaces() {
        guard !searchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        let request = MKLocalSearch.Request()
        request.naturalLanguageQuery = searchText
        MKLocalSearch(request: request).start { response, _ in
            guard let response else { return }
            searchResults = response.mapItems
            if let first = response.mapItems.first,
               let coordinate = first.placemark.location?.coordinate {
                selectedLocation = coordinate
                selectedName = first.name ?? AppStrings.selectedLocation
                position = .camera(MapCamera(centerCoordinate: coordinate, distance: 5000))
            }
        }
    }
}

struct MapsShareView: View {
    let onShare: (Double, Double, String) -> Void
    let onCancel: () -> Void

    var body: some View {
        ComposerLocationOverlay(onShare: onShare, onCancel: onCancel)
    }
}
