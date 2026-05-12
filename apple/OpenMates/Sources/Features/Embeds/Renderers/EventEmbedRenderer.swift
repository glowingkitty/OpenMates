// EventEmbedRenderer — native counterpart for a single events child embed.
// Mirrors the Svelte preview/fullscreen event cards used by events search,
// including date, location, attendance, fee, provider, and optional image.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/events/EventEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/events/EventEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI
#if canImport(MapKit)
import MapKit
#endif
#if os(iOS)
import UIKit
#endif

struct EventEmbedRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var event: EventResultSummary {
        EventResultSummary(embedId: nil, data: data ?? [:])
    }

    var body: some View {
        switch mode {
        case .preview:
            EventPreviewDetails(event: event)
        case .fullscreen:
            EventFullscreenDetails(event: event)
        }
    }
}

struct EventResultCard: View {
    let event: EventResultSummary

    var body: some View {
        EventPreviewDetails(event: event)
            .padding(.spacing5)
            .frame(maxWidth: .infinity, minHeight: 144, alignment: .leading)
            .background(Color.grey25)
            .clipShape(RoundedRectangle(cornerRadius: 30))
            .shadow(color: .black.opacity(0.12), radius: 20, x: 0, y: 8)
    }
}

private struct EventPreviewDetails: View {
    let event: EventResultSummary

    var body: some View {
        HStack(alignment: .center, spacing: .spacing5) {
            VStack(alignment: .leading, spacing: .spacing2) {
                Text(event.title)
                    .font(.omSmall)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.grey100)
                    .lineLimit(3)
                    .multilineTextAlignment(.leading)

                VStack(alignment: .leading, spacing: 1) {
                    if let date = event.shortDate {
                        Text(date)
                            .font(.omXs)
                            .fontWeight(.medium)
                            .foregroundStyle(Color.grey70)
                            .lineLimit(1)
                    }
                    if let location = event.shortLocation {
                        Text(location)
                            .font(.omXs)
                            .foregroundStyle(Color.grey60)
                            .lineLimit(1)
                    }
                }

                HStack(spacing: .spacing2) {
                    if let typeLabel = event.typeLabel {
                        EventTypeBadge(label: typeLabel, isOnline: event.isOnline, compact: true)
                    }
                    if let fee = event.feeText {
                        Text(fee)
                            .font(.omTiny)
                            .fontWeight(.semibold)
                            .foregroundStyle(Color.grey70)
                    } else if let rsvps = event.rsvpText {
                        Text(rsvps)
                            .font(.omTiny)
                            .foregroundStyle(Color.grey60)
                    }
                    if let provider = event.providerLabel {
                        Text(provider)
                            .font(.omTiny)
                            .foregroundStyle(Color.grey50)
                    }
                }
                .lineLimit(1)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            if let imageURL = event.imageURL, let url = URL(string: imageURL) {
                CachedRemoteImage(url: url) { image in
                    image.resizable().aspectRatio(contentMode: .fill)
                } placeholder: {
                    Color.grey20
                }
                .frame(width: 104, height: 126)
                .clipped()
            }
        }
        .padding(.vertical, .spacing4)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
    }
}

private struct EventFullscreenDetails: View {
    let event: EventResultSummary

    var body: some View {
        EmbedMapDetailTemplate(mapConfiguration: event.mapConfiguration) {
            eventDetailContent
        }
    }

    private var eventDetailContent: some View {
        VStack(alignment: .leading, spacing: .spacing8) {
            if let imageURL = event.imageURL, let url = URL(string: imageURL) {
                CachedRemoteImage(url: url) { image in
                    image.resizable().aspectRatio(contentMode: .fill)
                } placeholder: {
                    Color.grey20
                }
                .frame(height: 190)
                .clipShape(RoundedRectangle(cornerRadius: .radius5))
                .clipped()
            }

            HStack(spacing: .spacing4) {
                if let typeLabel = event.typeLabel {
                    EventTypeBadge(label: typeLabel, isOnline: event.isOnline, compact: false)
                }
                if let fee = event.feeText {
                    EventPill(label: fee, background: Color.grey20, foreground: Color.fontPrimary)
                } else if event.isPaid == false {
                    EventPill(label: "Free", background: Color(hex: 0x22C55E).opacity(0.15), foreground: Color.fontPrimary)
                }
                if let rsvps = event.rsvpText {
                    Text(rsvps)
                        .font(.omSmall)
                        .foregroundStyle(Color.grey60)
                }
                if let provider = event.providerLabel {
                    EventPill(label: provider, background: Color.grey10, foreground: Color.fontSecondary, stroke: Color.grey25)
                }
            }

            EventDetailSection(label: "Date & Time", values: event.dateTimeLines)

            if event.isOnline {
                EventDetailSection(label: "Location", values: ["Online event"])
            } else if !event.venueAddress.isEmpty {
                EventDetailSection(label: "Location", values: [event.venueAddress])
            }

            if let organizer = event.organizerName {
                EventDetailSection(label: "Organizer", values: [organizer])
            }

            if let description = event.description {
                VStack(alignment: .leading, spacing: .spacing2) {
                    Text("About")
                        .font(.omTiny)
                        .fontWeight(.semibold)
                        .foregroundStyle(Color.grey60)
                        .textCase(.uppercase)
                    Text(description)
                        .font(.omP)
                        .foregroundStyle(Color.fontPrimary)
                        .lineSpacing(4)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

#if canImport(MapKit)
struct EmbedMapConfiguration {
    let center: CLLocationCoordinate2D
    let markers: [EmbedMapMarker]
    var route: [CLLocationCoordinate2D] = []
    var latitudeDelta: CLLocationDegrees = 0.025
    var longitudeDelta: CLLocationDegrees = 0.025
}

struct EmbedMapMarker: Identifiable {
    let id = UUID()
    let coordinate: CLLocationCoordinate2D
    let title: String
}
#endif

struct EmbedMapDetailTemplate<Content: View>: View {
    #if canImport(MapKit)
    let mapConfiguration: EmbedMapConfiguration?
    #else
    let mapConfiguration: Never?
    #endif
    @ViewBuilder let content: () -> Content

    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    private var usesWideMapLayout: Bool {
        horizontalSizeClass != .compact
    }

    var body: some View {
        #if canImport(MapKit)
        if let mapConfiguration {
            if usesWideMapLayout {
                ZStack(alignment: .topLeading) {
                    EmbedFullscreenMapView(configuration: mapConfiguration)

                    detailCard
                        .frame(width: 345)
                        .padding(.top, .spacing8)
                        .padding(.leading, .spacing8)
                }
                .frame(maxWidth: .infinity, minHeight: 540, alignment: .topLeading)
            } else {
                VStack(spacing: 0) {
                    EmbedFullscreenMapView(configuration: mapConfiguration)
                        .frame(height: 150)
                    detailCard
                }
                .frame(maxWidth: .infinity, alignment: .top)
            }
        } else {
            detailCard
                .padding(.horizontal, .spacing8)
                .padding(.vertical, .spacing10)
        }
        #else
        detailCard
            .padding(.horizontal, .spacing8)
            .padding(.vertical, .spacing10)
        #endif
    }

    private var detailCard: some View {
        content()
            .padding(.spacing10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.grey20)
            .clipShape(RoundedRectangle(cornerRadius: usesWideMapLayout ? .radius7 : 0))
            .shadow(color: usesWideMapLayout ? .black.opacity(0.15) : .clear, radius: 24, x: 0, y: 4)
    }
}

#if canImport(MapKit)
private struct EmbedFullscreenMapView: View {
    let configuration: EmbedMapConfiguration
    @State private var position: MapCameraPosition
    @State private var currentRegion: MKCoordinateRegion
    @State private var mapRefreshID = UUID()
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    init(configuration: EmbedMapConfiguration) {
        self.configuration = configuration
        let initialRegion = Self.region(for: configuration)
        _position = State(initialValue: .region(initialRegion))
        _currentRegion = State(initialValue: initialRegion)
    }

    var body: some View {
        ZStack(alignment: zoomControlAlignment) {
            #if os(iOS)
            EmbedMKMapView(configuration: configuration, region: $currentRegion)
                .zIndex(0)
            #else
            Map(position: $position, interactionModes: .all) {
                if configuration.route.count > 1 {
                    MapPolyline(coordinates: configuration.route)
                        .stroke(Color.buttonPrimary, lineWidth: 4)
                }
                ForEach(configuration.markers) { marker in
                    Annotation(marker.title, coordinate: marker.coordinate) {
                        Icon("pin", size: 40)
                            .foregroundStyle(Color.buttonPrimary)
                            .shadow(color: .black.opacity(0.28), radius: 7, x: 0, y: 3)
                            .offset(y: -20)
                    }
                }
            }
            .id(mapRefreshID)
            .mapControlVisibility(.hidden)
            .onMapCameraChange { context in
                currentRegion = context.region
            }
            .zIndex(0)
            #endif

            zoomControls
                .padding(.trailing, horizontalSizeClass == .compact ? 12 : .spacing8)
                .padding(.top, horizontalSizeClass == .compact ? 12 : 0)
                .contentShape(Rectangle())
                .allowsHitTesting(true)
                .zIndex(10)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var zoomControlAlignment: Alignment {
        horizontalSizeClass == .compact ? .topTrailing : .trailing
    }

    private var zoomControls: some View {
        VStack(spacing: 0) {
            mapControlButton(iconName: "plus", accessibilityLabel: AppStrings.zoomIn) {
                zoom(by: 0.35)
            }

            Rectangle()
                .fill(Color.grey30)
                .frame(width: 30, height: 1)

            mapControlButton(iconName: "minus", accessibilityLabel: AppStrings.zoomOut) {
                zoom(by: 2.85)
            }
        }
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: .radius3))
        .overlay {
            RoundedRectangle(cornerRadius: .radius3)
                .stroke(Color.black.opacity(0.18), lineWidth: 1)
        }
        .shadow(color: .black.opacity(0.15), radius: 8, x: 0, y: 2)
    }

    private func mapControlButton(iconName: String, accessibilityLabel: String, action: @escaping () -> Void) -> some View {
        Icon(iconName, size: 18)
            .foregroundStyle(Color.black.opacity(0.78))
            .frame(width: 30, height: 30)
            .background(Color.white)
            .contentShape(Rectangle())
            .onTapGesture(perform: action)
            .accessibilityAddTraits(.isButton)
            .accessibilityAction { action() }
        .accessibilityLabel(accessibilityLabel)
    }

    private func zoom(by factor: CLLocationDegrees) {
        var region = currentRegion
        region.span.latitudeDelta = max(min(region.span.latitudeDelta * factor, 120), 0.002)
        region.span.longitudeDelta = max(min(region.span.longitudeDelta * factor, 120), 0.002)
        currentRegion = region
        #if os(iOS)
        mapRefreshID = UUID()
        #else
        withAnimation(.easeInOut(duration: 0.18)) {
            position = .region(region)
        }
        mapRefreshID = UUID()
        #endif
    }

    private static func region(for configuration: EmbedMapConfiguration) -> MKCoordinateRegion {
        let coordinates = (configuration.route + configuration.markers.map(\.coordinate))
        guard coordinates.count > 1 else {
            return MKCoordinateRegion(
                center: configuration.center,
                span: MKCoordinateSpan(
                    latitudeDelta: configuration.latitudeDelta,
                    longitudeDelta: configuration.longitudeDelta
                )
            )
        }

        let latitudes = coordinates.map(\.latitude)
        let longitudes = coordinates.map(\.longitude)
        let minLat = latitudes.min() ?? configuration.center.latitude
        let maxLat = latitudes.max() ?? configuration.center.latitude
        let minLon = longitudes.min() ?? configuration.center.longitude
        let maxLon = longitudes.max() ?? configuration.center.longitude
        let center = CLLocationCoordinate2D(latitude: (minLat + maxLat) / 2, longitude: (minLon + maxLon) / 2)
        return MKCoordinateRegion(
            center: center,
            span: MKCoordinateSpan(
                latitudeDelta: max((maxLat - minLat) * 1.45, configuration.latitudeDelta),
                longitudeDelta: max((maxLon - minLon) * 1.45, configuration.longitudeDelta)
            )
        )
    }
}

#if os(iOS)
private struct EmbedMKMapView: UIViewRepresentable {
    let configuration: EmbedMapConfiguration
    @Binding var region: MKCoordinateRegion

    func makeCoordinator() -> Coordinator {
        Coordinator(region: $region)
    }

    func makeUIView(context: Context) -> MKMapView {
        let mapView = MKMapView()
        mapView.delegate = context.coordinator
        mapView.mapType = .standard
        mapView.isZoomEnabled = true
        mapView.isScrollEnabled = true
        mapView.isRotateEnabled = false
        mapView.isPitchEnabled = false
        mapView.showsCompass = false
        mapView.showsScale = false
        mapView.pointOfInterestFilter = .includingAll
        return mapView
    }

    func updateUIView(_ mapView: MKMapView, context: Context) {
        context.coordinator.parent = self
        context.coordinator.syncMapAnnotations(on: mapView)
        context.coordinator.syncMapOverlays(on: mapView)
        if !context.coordinator.region(mapView.region, isCloseTo: region) {
            context.coordinator.isProgrammaticRegionChange = true
            mapView.setRegion(region, animated: true)
            DispatchQueue.main.async {
                context.coordinator.isProgrammaticRegionChange = false
            }
        }
    }

    final class Coordinator: NSObject, MKMapViewDelegate {
        var parent: EmbedMKMapView?
        @Binding var region: MKCoordinateRegion
        var isProgrammaticRegionChange = false

        init(region: Binding<MKCoordinateRegion>) {
            _region = region
        }

        func mapView(_ mapView: MKMapView, regionDidChangeAnimated animated: Bool) {
            guard !isProgrammaticRegionChange else { return }
            region = mapView.region
        }

        func mapView(_ mapView: MKMapView, viewFor annotation: MKAnnotation) -> MKAnnotationView? {
            guard !(annotation is MKUserLocation) else { return nil }
            let identifier = "embed-map-pin"
            let annotationView = mapView.dequeueReusableAnnotationView(withIdentifier: identifier)
                ?? MKAnnotationView(annotation: annotation, reuseIdentifier: identifier)
            annotationView.annotation = annotation
            annotationView.image = UIImage(named: "pin")?.withRenderingMode(.alwaysTemplate)
            annotationView.tintColor = UIColor(Color.buttonPrimary)
            annotationView.centerOffset = CGPoint(x: 0, y: -20)
            annotationView.canShowCallout = false
            annotationView.frame.size = CGSize(width: 40, height: 40)
            return annotationView
        }

        func mapView(_ mapView: MKMapView, rendererFor overlay: MKOverlay) -> MKOverlayRenderer {
            if let polyline = overlay as? MKPolyline {
                let renderer = MKPolylineRenderer(polyline: polyline)
                renderer.strokeColor = UIColor(Color.buttonPrimary)
                renderer.lineWidth = 4
                return renderer
            }
            return MKOverlayRenderer(overlay: overlay)
        }

        func syncMapAnnotations(on mapView: MKMapView) {
            guard let parent else { return }
            mapView.removeAnnotations(mapView.annotations.filter { !($0 is MKUserLocation) })
            let annotations = parent.configuration.markers.map { marker in
                let annotation = MKPointAnnotation()
                annotation.coordinate = marker.coordinate
                annotation.title = marker.title
                return annotation
            }
            mapView.addAnnotations(annotations)
        }

        func syncMapOverlays(on mapView: MKMapView) {
            guard let parent else { return }
            mapView.removeOverlays(mapView.overlays)
            if parent.configuration.route.count > 1 {
                mapView.addOverlay(MKPolyline(coordinates: parent.configuration.route, count: parent.configuration.route.count))
            }
        }

        func region(_ lhs: MKCoordinateRegion, isCloseTo rhs: MKCoordinateRegion) -> Bool {
            abs(lhs.center.latitude - rhs.center.latitude) < 0.000_001
                && abs(lhs.center.longitude - rhs.center.longitude) < 0.000_001
                && abs(lhs.span.latitudeDelta - rhs.span.latitudeDelta) < 0.000_001
                && abs(lhs.span.longitudeDelta - rhs.span.longitudeDelta) < 0.000_001
        }
    }
}
#endif
#endif

private struct EventDetailSection: View {
    let label: String
    let values: [String]

    var body: some View {
        if !values.isEmpty {
            VStack(alignment: .leading, spacing: .spacing2) {
                Text(label)
                    .font(.omTiny)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.grey60)
                    .textCase(.uppercase)
                ForEach(values, id: \.self) { value in
                    Text(value)
                        .font(.omP)
                        .foregroundStyle(Color.fontPrimary)
                        .lineSpacing(4)
                }
            }
        }
    }
}

private struct EventTypeBadge: View {
    let label: String
    let isOnline: Bool
    let compact: Bool

    var body: some View {
        Text(label.uppercased())
            .font(compact ? .omMicro : .omXs)
            .fontWeight(.semibold)
            .foregroundStyle(Color.grey0)
            .padding(.horizontal, compact ? .spacing4 : .spacing6)
            .padding(.vertical, compact ? .spacing1 : .spacing2)
            .background(isOnline ? Color(hex: 0x1A6B5A) : Color(hex: 0xA20000))
            .clipShape(Capsule())
    }
}

private struct EventPill: View {
    let label: String
    let background: Color
    let foreground: Color
    var stroke: Color?

    var body: some View {
        Text(label)
            .font(.omXs)
            .fontWeight(.semibold)
            .foregroundStyle(foreground)
            .padding(.horizontal, .spacing6)
            .padding(.vertical, .spacing2)
            .background(background)
            .clipShape(Capsule())
            .overlay {
                if let stroke {
                    Capsule().stroke(stroke, lineWidth: 1)
                }
            }
    }
}

struct EventResultSummary: Identifiable {
    let id = UUID()
    let embedId: String?
    let title: String
    let description: String?
    let provider: String?
    let dateStart: String?
    let dateEnd: String?
    let eventType: String?
    let venueName: String?
    let venueAddressLine: String?
    let venueCity: String?
    let venueState: String?
    let venueCountry: String?
    let organizerName: String?
    let rsvpCount: Int?
    let isPaid: Bool?
    let feeAmount: Double?
    let feeCurrency: String?
    let imageURL: String?
    let venueLatitude: Double?
    let venueLongitude: Double?

    init(embedId: String?, data: [String: AnyCodable]) {
        self.embedId = embedId
        self.title = EventValue.string(data, ["title", "name"]) ?? "Event"
        self.description = EventValue.string(data, ["description"])
        self.provider = EventValue.string(data, ["provider", "source"])
        self.dateStart = EventValue.string(data, ["date_start", "date"])
        self.dateEnd = EventValue.string(data, ["date_end"])
        self.eventType = EventValue.string(data, ["event_type"])
        self.venueName = EventValue.nestedString(data, objectKey: "venue", keys: ["name"]) ?? EventValue.string(data, ["venue_name"])
        self.venueAddressLine = EventValue.nestedString(data, objectKey: "venue", keys: ["address"]) ?? EventValue.string(data, ["venue_address"])
        self.venueCity = EventValue.nestedString(data, objectKey: "venue", keys: ["city"]) ?? EventValue.string(data, ["venue_city", "city"])
        self.venueState = EventValue.nestedString(data, objectKey: "venue", keys: ["state"]) ?? EventValue.string(data, ["venue_state"])
        self.venueCountry = EventValue.nestedString(data, objectKey: "venue", keys: ["country"]) ?? EventValue.string(data, ["venue_country", "country"])
        self.organizerName = EventValue.nestedString(data, objectKey: "organizer", keys: ["name"]) ?? EventValue.string(data, ["organizer_name"])
        self.rsvpCount = EventValue.int(data, ["rsvp_count"])
        self.isPaid = EventValue.bool(data, ["is_paid"])
        self.feeAmount = EventValue.nestedDouble(data, objectKey: "fee", keys: ["amount"]) ?? EventValue.double(data, ["fee_amount"])
        self.feeCurrency = EventValue.nestedString(data, objectKey: "fee", keys: ["currency"]) ?? EventValue.string(data, ["fee_currency"])
        self.imageURL = EventValue.directOrProxiedImage(data, keys: ["image_url", "cover_url"], maxWidth: 520)
        self.venueLatitude = EventValue.nestedDouble(data, objectKey: "venue", keys: ["lat", "latitude"])
            ?? EventValue.double(data, ["venue_lat", "lat", "latitude"])
        self.venueLongitude = EventValue.nestedDouble(data, objectKey: "venue", keys: ["lon", "lng", "longitude"])
            ?? EventValue.double(data, ["venue_lon", "venue_lng", "lon", "lng", "longitude"])
    }

    var isOnline: Bool {
        eventType == "ONLINE"
    }

    var typeLabel: String? {
        guard let eventType, !eventType.isEmpty else { return nil }
        return isOnline ? "Online" : "In Person"
    }

    var shortDate: String? {
        EventValue.formatShortDate(dateStart)
    }

    var shortLocation: String? {
        if isOnline { return "Online" }
        let locationParts: [String?] = [venueCity, venueCountry]
        let parts = locationParts.compactMap { $0 }.filter { !$0.isEmpty }
        return parts.isEmpty ? nil : parts.joined(separator: ", ")
    }

    var venueAddress: String {
        var parts: [String] = []
        if let venueName, !venueName.isEmpty { parts.append(venueName) }
        if let venueAddressLine, !venueAddressLine.isEmpty { parts.append(venueAddressLine) }
        let cityLineValues: [String?] = [venueCity, venueState, venueCountry]
        let cityLine = cityLineValues.compactMap { $0 }.filter { !$0.isEmpty }
        if !cityLine.isEmpty { parts.append(cityLine.joined(separator: ", ")) }
        return parts.joined(separator: "\n")
    }

    var providerLabel: String? {
        guard let provider, !provider.isEmpty else { return nil }
        switch provider.lowercased() {
        case "meetup": return "Meetup"
        case "luma": return "Luma"
        case "google_events": return "Google"
        case "resident_advisor": return "Resident Advisor"
        case "siegessaeule": return "Siegessäule"
        case "classictic": return "Classictic"
        case "berlin_philharmonic": return "Berlin Philharmonic"
        case "bachtrack": return "Bachtrack"
        case "eventbrite": return "Eventbrite"
        default: return provider
        }
    }

    var rsvpText: String? {
        guard let rsvpCount, rsvpCount > 0 else { return nil }
        return "\(rsvpCount.formatted()) RSVPs"
    }

    var feeText: String? {
        guard isPaid == true, let feeAmount else { return nil }
        let currency = feeCurrency ?? ""
        return currency.isEmpty ? String(format: "%.0f", feeAmount) : "\(currency) \(String(format: feeAmount.rounded() == feeAmount ? "%.0f" : "%.2f", feeAmount))"
    }

    var dateTimeLines: [String] {
        guard let dateStart else { return [] }
        var lines = [EventValue.formatLongDate(dateStart)]
        if let time = EventValue.formatTimeRange(start: dateStart, end: dateEnd), !time.isEmpty {
            lines.append(time)
        }
        return lines.filter { !$0.isEmpty }
    }

    #if canImport(MapKit)
    var coordinate: CLLocationCoordinate2D? {
        guard !isOnline,
              let venueLatitude,
              let venueLongitude,
              CLLocationCoordinate2DIsValid(CLLocationCoordinate2D(latitude: venueLatitude, longitude: venueLongitude))
        else { return nil }
        return CLLocationCoordinate2D(latitude: venueLatitude, longitude: venueLongitude)
    }

    var mapConfiguration: EmbedMapConfiguration? {
        guard let coordinate else { return nil }
        return EmbedMapConfiguration(
            center: coordinate,
            markers: [EmbedMapMarker(coordinate: coordinate, title: venueName ?? title)]
        )
    }
    #else
    var mapConfiguration: Never? { nil }
    #endif
}

enum EventValue {
    static func string(_ data: [String: AnyCodable], _ keys: [String]) -> String? {
        for key in keys {
            if let value = data[key]?.value as? String, !value.isEmpty, value != "null" { return value }
            if let value = data[key]?.value as? Int { return String(value) }
            if let value = data[key]?.value as? Double { return String(value) }
        }
        return nil
    }

    static func int(_ data: [String: AnyCodable], _ keys: [String]) -> Int? {
        for key in keys {
            if let value = data[key]?.value as? Int { return value }
            if let value = data[key]?.value as? Double { return Int(value) }
            if let value = data[key]?.value as? String, let int = Int(value) { return int }
        }
        return nil
    }

    static func double(_ data: [String: AnyCodable], _ keys: [String]) -> Double? {
        for key in keys {
            if let value = data[key]?.value as? Double { return value }
            if let value = data[key]?.value as? Int { return Double(value) }
            if let value = data[key]?.value as? String {
                return Double(value) ?? Double(value.replacingOccurrences(of: ",", with: "."))
            }
        }
        return nil
    }

    static func bool(_ data: [String: AnyCodable], _ keys: [String]) -> Bool? {
        for key in keys {
            if let value = data[key]?.value as? Bool { return value }
            if let value = data[key]?.value as? String {
                if value == "true" { return true }
                if value == "false" { return false }
            }
        }
        return nil
    }

    static func nestedString(_ data: [String: AnyCodable], objectKey: String, keys: [String]) -> String? {
        guard let object = data[objectKey]?.value as? [String: Any] else { return nil }
        return string(object.mapValues(AnyCodable.init), keys)
    }

    static func nestedDouble(_ data: [String: AnyCodable], objectKey: String, keys: [String]) -> Double? {
        guard let object = data[objectKey]?.value as? [String: Any] else { return nil }
        return double(object.mapValues(AnyCodable.init), keys)
    }

    static func directOrProxiedImage(_ data: [String: AnyCodable], keys: [String], maxWidth: Int) -> String? {
        guard let rawURL = string(data, keys) else { return nil }
        if URL(string: rawURL)?.scheme?.hasPrefix("http") == true {
            return rawURL
        }
        return EmbedFieldReader.proxiedImageURL(rawURL, maxWidth: maxWidth)
    }

    static func formatShortDate(_ value: String?) -> String? {
        guard let value, let date = parseDate(value) else { return nil }
        let formatter = DateFormatter()
        formatter.locale = Locale.current
        formatter.dateFormat = "MMM d - h:mm a"
        return formatter.string(from: date)
    }

    static func formatLongDate(_ value: String) -> String {
        guard let date = parseDate(value) else { return value }
        let formatter = DateFormatter()
        formatter.locale = Locale.current
        formatter.dateFormat = "EEEE, MMMM d, yyyy"
        return formatter.string(from: date)
    }

    static func formatTimeRange(start: String, end: String?) -> String? {
        guard let startDate = parseDate(start) else { return nil }
        let formatter = DateFormatter()
        formatter.locale = Locale.current
        formatter.dateFormat = "h:mm a"
        let startText = formatter.string(from: startDate)
        guard let end, let endDate = parseDate(end) else { return startText }
        return "\(startText) to \(formatter.string(from: endDate))"
    }

    private static func parseDate(_ value: String) -> Date? {
        let isoFormatter = ISO8601DateFormatter()
        if let date = isoFormatter.date(from: value) { return date }

        let fractionalISOFormatter = ISO8601DateFormatter()
        fractionalISOFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = fractionalISOFormatter.date(from: value) { return date }

        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        for format in ["yyyy-MM-dd'T'HH:mm:ss.SSSXXXXX", "yyyy-MM-dd'T'HH:mm:ss.SSS", "yyyy-MM-dd'T'HH:mm:ssXXXXX", "yyyy-MM-dd'T'HH:mm:ss", "yyyy-MM-dd HH:mm", "yyyy-MM-dd"] {
            formatter.dateFormat = format
            if let date = formatter.date(from: value) { return date }
        }
        return nil
    }
}
