// Travel embed renderers — connections, stays, price calendar, flights.

import SwiftUI

struct TravelConnectionRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var departure: String { data?["departure"]?.value as? String ?? "" }
    private var arrival: String { data?["arrival"]?.value as? String ?? "" }
    private var price: Double? { data?["price"]?.value as? Double }
    private var currency: String { data?["currency"]?.value as? String ?? "€" }
    private var duration: String? { data?["duration"]?.value as? String }
    private var transfers: Int? { data?["transfers"]?.value as? Int }
    private var carrier: String? { data?["carrier"]?.value as? String }

    var body: some View {
        switch mode {
        case .preview:
            VStack(alignment: .leading, spacing: .spacing3) {
                HStack {
                    Text(departure).font(.omSmall).fontWeight(.medium)
                    Image(systemName: "arrow.right").font(.caption)
                    Text(arrival).font(.omSmall).fontWeight(.medium)
                }
                .foregroundStyle(Color.fontPrimary)

                HStack(spacing: .spacing4) {
                    if let price {
                        Text("\(currency)\(String(format: "%.0f", price))")
                            .font(.omP).fontWeight(.bold).foregroundStyle(Color.fontPrimary)
                    }
                    if let duration {
                        Label(duration, systemImage: SFSymbol.clock)
                            .font(.omXs).foregroundStyle(Color.fontTertiary)
                    }
                }

                if let carrier {
                    Text(carrier).font(.omXs).foregroundStyle(Color.fontTertiary)
                }
            }
            .padding(.spacing4)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing6) {
                HStack(spacing: .spacing4) {
                    VStack { Text(departure).font(.omH3).fontWeight(.bold) }
                    Image(systemName: "airplane").font(.title2).foregroundStyle(Color.fontTertiary)
                    VStack { Text(arrival).font(.omH3).fontWeight(.bold) }
                }
                .foregroundStyle(Color.fontPrimary)

                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: .spacing4) {
                    if let price { detailItem("Price", "\(currency)\(String(format: "%.2f", price))") }
                    if let duration { detailItem("Duration", duration) }
                    if let transfers { detailItem("Transfers", transfers == 0 ? "Direct" : "\(transfers)") }
                    if let carrier { detailItem("Carrier", carrier) }
                }
            }
        }
    }

    private func detailItem(_ label: String, _ value: String) -> some View {
        VStack(alignment: .leading, spacing: .spacing1) {
            Text(label).font(.omXs).foregroundStyle(Color.fontTertiary)
            Text(value).font(.omP).fontWeight(.medium).foregroundStyle(Color.fontPrimary)
        }
    }
}

struct TravelStayRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var name: String { data?["name"]?.value as? String ?? "Stay" }
    private var location: String? { data?["location"]?.value as? String }
    private var pricePerNight: Double? { data?["price_per_night"]?.value as? Double }
    private var currency: String { data?["currency"]?.value as? String ?? "€" }
    private var rating: Double? { data?["rating"]?.value as? Double }
    private var imageUrl: String? { data?["image_url"]?.value as? String }

    var body: some View {
        switch mode {
        case .preview:
            ZStack(alignment: .bottomLeading) {
                if let imageUrl, let imgURL = URL(string: imageUrl) {
                    AsyncImage(url: imgURL) { image in
                        image.resizable().aspectRatio(contentMode: .fill)
                    } placeholder: {
                        Color.grey20
                    }
                } else {
                    Color.grey20.overlay(Image(systemName: "bed.double.fill").font(.largeTitle).foregroundStyle(Color.fontTertiary))
                }

                VStack(alignment: .leading, spacing: 2) {
                    Text(name).font(.omSmall).fontWeight(.medium).foregroundStyle(.white).lineLimit(1)
                    HStack {
                        if let pricePerNight {
                            Text("\(currency)\(String(format: "%.0f", pricePerNight))/night")
                                .font(.omXs).foregroundStyle(.white)
                        }
                        if let rating {
                            Label(String(format: "%.1f", rating), systemImage: "star.fill")
                                .font(.omTiny).foregroundStyle(.yellow)
                        }
                    }
                }
                .padding(.spacing3)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(.linearGradient(colors: [.clear, .black.opacity(0.7)], startPoint: .top, endPoint: .bottom))
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

        case .fullscreen:
            VStack(alignment: .leading, spacing: .spacing4) {
                if let imageUrl, let imgURL = URL(string: imageUrl) {
                    AsyncImage(url: imgURL) { image in
                        image.resizable().aspectRatio(contentMode: .fit)
                    } placeholder: { ProgressView() }
                    .clipShape(RoundedRectangle(cornerRadius: .radius3))
                }
                if let location { Label(location, systemImage: "mappin").font(.omSmall).foregroundStyle(Color.fontSecondary) }
                if let pricePerNight {
                    Text("\(currency)\(String(format: "%.2f", pricePerNight)) per night")
                        .font(.omH4).fontWeight(.bold).foregroundStyle(Color.fontPrimary)
                }
                if let rating {
                    HStack {
                        ForEach(0..<Int(rating), id: \.self) { _ in
                            Image(systemName: "star.fill").foregroundStyle(.yellow)
                        }
                        Text(String(format: "%.1f", rating)).font(.omSmall).foregroundStyle(Color.fontSecondary)
                    }
                }
            }
        }
    }
}

struct TravelPriceCalendarRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var origin: String? { data?["origin"]?.value as? String }
    private var destination: String? { data?["destination"]?.value as? String }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Image(systemName: "calendar.badge.clock")
                .font(.system(size: mode == .preview ? 24 : 32))
                .foregroundStyle(Color.fontTertiary)
            if let origin, let destination {
                Text("\(origin) → \(destination)")
                    .font(mode == .preview ? .omSmall : .omP)
                    .foregroundStyle(Color.fontPrimary)
            }
            Text(LocalizationManager.shared.text("embed.travel.price_calendar"))
                .font(.omXs).foregroundStyle(Color.fontSecondary)
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: mode == .preview ? .infinity : nil, alignment: .topLeading)
    }
}

struct TravelFlightRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var airline: String? { data?["airline"]?.value as? String }
    private var flightNumber: String? { data?["flight_number"]?.value as? String }
    private var departure: String? { data?["departure"]?.value as? String }
    private var arrival: String? { data?["arrival"]?.value as? String }
    private var duration: String? { data?["duration"]?.value as? String }
    private var price: Double? { data?["price"]?.value as? Double }
    private var currency: String { data?["currency"]?.value as? String ?? "€" }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if let airline {
                Text(airline).font(mode == .preview ? .omSmall : .omH4)
                    .fontWeight(.medium).foregroundStyle(Color.fontPrimary)
            }
            if let flightNumber {
                Text(flightNumber).font(.omXs).foregroundStyle(Color.fontTertiary)
            }
            if let departure, let arrival {
                HStack {
                    Text(departure)
                    Image(systemName: "arrow.right").font(.caption)
                    Text(arrival)
                }
                .font(.omSmall).foregroundStyle(Color.fontSecondary)
            }
            if let price {
                Text("\(currency)\(String(format: "%.0f", price))")
                    .font(.omP).fontWeight(.bold).foregroundStyle(Color.fontPrimary)
            }
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: mode == .preview ? .infinity : nil, alignment: .topLeading)
    }
}
