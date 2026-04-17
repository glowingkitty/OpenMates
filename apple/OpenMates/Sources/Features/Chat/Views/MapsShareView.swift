// Maps location sharing — pick a location on a map to share in chat.
// Mirrors the web app's enter_message/MapsView.svelte.
// Uses MapKit for native Apple Maps integration with search and pin drop.

import SwiftUI
import MapKit

struct MapsShareView: View {
    let onShare: (Double, Double, String) -> Void
    let onCancel: () -> Void

    @State private var position: MapCameraPosition = .automatic
    @State private var selectedLocation: CLLocationCoordinate2D?
    @State private var selectedName: String = ""
    @State private var searchText = ""
    @State private var searchResults: [MKMapItem] = []
    @State private var isSearching = false

    var body: some View {
        NavigationStack {
            ZStack {
                Map(position: $position, selection: $selectedLocation) {
                    if let loc = selectedLocation {
                        Marker(selectedName.isEmpty ? "Selected" : selectedName, coordinate: loc)
                            .tint(.red)
                    }
                    ForEach(searchResults, id: \.self) { item in
                        if let coord = item.placemark.location?.coordinate {
                            Marker(
                                item.name ?? "Location",
                                coordinate: coord
                            )
                        }
                    }
                }
                .mapStyle(.standard(elevation: .realistic))
                .onTapGesture { location in
                    // MapKit tap-to-pin requires MapReader in iOS 17+
                }

                VStack {
                    searchBar
                    Spacer()
                    if selectedLocation != nil {
                        shareButton
                    }
                }
            }
            .navigationTitle("Share Location")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { onCancel() }
                }
            }
        }
    }

    private var searchBar: some View {
        HStack {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(Color.fontTertiary)
            TextField("Search places", text: $searchText)
                .autocorrectionDisabled()
                .onSubmit { searchPlaces() }
        }
        .padding(.spacing3)
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: .radius4))
        .padding(.horizontal)
        .padding(.top, .spacing2)
    }

    private var shareButton: some View {
        Button {
            if let loc = selectedLocation {
                onShare(loc.latitude, loc.longitude, selectedName)
            }
        } label: {
            HStack {
                Image(systemName: "location.fill")
                Text("Share Location")
                    .fontWeight(.medium)
            }
            .frame(maxWidth: .infinity)
            .padding(.spacing3)
        }
        .buttonStyle(.borderedProminent)
        .tint(Color.buttonPrimary)
        .padding(.horizontal)
        .padding(.bottom, .spacing4)
    }

    private func searchPlaces() {
        guard !searchText.isEmpty else { return }
        isSearching = true

        let request = MKLocalSearch.Request()
        request.naturalLanguageQuery = searchText

        let search = MKLocalSearch(request: request)
        search.start { response, error in
            isSearching = false
            guard let response else { return }

            searchResults = response.mapItems
            if let first = response.mapItems.first,
               let coord = first.placemark.location?.coordinate {
                selectedLocation = coord
                selectedName = first.name ?? searchText
                position = .camera(MapCamera(centerCoordinate: coord, distance: 5000))
            }
        }
    }
}
