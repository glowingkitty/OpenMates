// Maps, events, health, home, nutrition, shopping embed renderers.

import SwiftUI

struct MapsPlaceRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var name: String { data?["name"]?.value as? String ?? "Place" }
    private var address: String? { data?["address"]?.value as? String }
    private var rating: Double? { data?["rating"]?.value as? Double }
    private var category: String? { data?["category"]?.value as? String }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Image(systemName: "mappin.circle.fill")
                .font(.system(size: mode == .preview ? 24 : 32))
                .foregroundStyle(Color.buttonPrimary)
            Text(name).font(mode == .preview ? .omSmall : .omH4).fontWeight(.medium)
                .foregroundStyle(Color.fontPrimary).lineLimit(mode == .preview ? 1 : nil)
            if let address {
                Text(address).font(.omXs).foregroundStyle(Color.fontSecondary)
                    .lineLimit(mode == .preview ? 2 : nil)
            }
            if let rating {
                HStack(spacing: 2) {
                    Image(systemName: "star.fill").foregroundStyle(.yellow).font(.caption)
                    Text(String(format: "%.1f", rating)).font(.omXs).foregroundStyle(Color.fontSecondary)
                }
            }
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: mode == .preview ? .infinity : nil, alignment: .topLeading)
    }
}

struct MapsLocationRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    var body: some View {
        MapsPlaceRenderer(data: data, mode: mode)
    }
}

struct EventRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var title: String { data?["title"]?.value as? String ?? "Event" }
    private var date: String? { data?["date"]?.value as? String }
    private var location: String? { data?["location"]?.value as? String }
    private var price: String? { data?["price"]?.value as? String }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Text(title).font(mode == .preview ? .omSmall : .omH4).fontWeight(.medium)
                .foregroundStyle(Color.fontPrimary).lineLimit(mode == .preview ? 2 : nil)
            if let date {
                Label(date, systemImage: "calendar").font(.omXs).foregroundStyle(Color.fontSecondary)
            }
            if let location {
                Label(location, systemImage: "mappin").font(.omXs).foregroundStyle(Color.fontTertiary)
                    .lineLimit(mode == .preview ? 1 : nil)
            }
            if let price {
                Text(price).font(.omSmall).fontWeight(.medium).foregroundStyle(Color.fontPrimary)
            }
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: mode == .preview ? .infinity : nil, alignment: .topLeading)
    }
}

struct AppointmentRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var doctorName: String? { data?["doctor_name"]?.value as? String }
    private var specialty: String? { data?["specialty"]?.value as? String }
    private var date: String? { data?["date"]?.value as? String }
    private var location: String? { data?["location"]?.value as? String }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if let doctorName {
                Text(doctorName).font(mode == .preview ? .omSmall : .omH4).fontWeight(.medium)
                    .foregroundStyle(Color.fontPrimary)
            }
            if let specialty {
                Text(specialty).font(.omXs).foregroundStyle(Color.fontSecondary)
            }
            if let date {
                Label(date, systemImage: "calendar").font(.omXs).foregroundStyle(Color.fontTertiary)
            }
            if let location {
                Label(location, systemImage: "mappin").font(.omXs).foregroundStyle(Color.fontTertiary)
            }
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: mode == .preview ? .infinity : nil, alignment: .topLeading)
    }
}

struct HomeListingRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var title: String { data?["title"]?.value as? String ?? "Listing" }
    private var price: Double? { data?["price"]?.value as? Double }
    private var currency: String { data?["currency"]?.value as? String ?? "€" }
    private var rooms: Int? { data?["rooms"]?.value as? Int }
    private var area: Double? { data?["area"]?.value as? Double }
    private var address: String? { data?["address"]?.value as? String }
    private var imageUrl: String? { data?["image_url"]?.value as? String }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if mode == .fullscreen, let imageUrl, let imgURL = URL(string: imageUrl) {
                AsyncImage(url: imgURL) { image in
                    image.resizable().aspectRatio(contentMode: .fit)
                } placeholder: { ProgressView() }
                .clipShape(RoundedRectangle(cornerRadius: .radius3))
            }
            Text(title).font(mode == .preview ? .omSmall : .omH4).fontWeight(.medium)
                .foregroundStyle(Color.fontPrimary).lineLimit(mode == .preview ? 2 : nil)
            if let price {
                Text("\(currency)\(String(format: "%.0f", price))")
                    .font(.omP).fontWeight(.bold).foregroundStyle(Color.fontPrimary)
            }
            HStack(spacing: .spacing4) {
                if let rooms { Label("\(rooms) rooms", systemImage: "door.left.hand.open").font(.omXs) }
                if let area { Label("\(String(format: "%.0f", area))m²", systemImage: "square.dashed").font(.omXs) }
            }
            .foregroundStyle(Color.fontTertiary)
            if let address {
                Label(address, systemImage: "mappin").font(.omXs).foregroundStyle(Color.fontTertiary)
                    .lineLimit(mode == .preview ? 1 : nil)
            }
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: mode == .preview ? .infinity : nil, alignment: .topLeading)
    }
}

struct RecipeRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var title: String { data?["title"]?.value as? String ?? "Recipe" }
    private var prepTime: String? { data?["prep_time"]?.value as? String }
    private var servings: Int? { data?["servings"]?.value as? Int }
    private var calories: Int? { data?["calories"]?.value as? Int }
    private var imageUrl: String? { data?["image_url"]?.value as? String }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if mode == .fullscreen, let imageUrl, let imgURL = URL(string: imageUrl) {
                AsyncImage(url: imgURL) { image in
                    image.resizable().aspectRatio(contentMode: .fit)
                } placeholder: { ProgressView() }
                .clipShape(RoundedRectangle(cornerRadius: .radius3))
            }
            Text(title).font(mode == .preview ? .omSmall : .omH4).fontWeight(.medium)
                .foregroundStyle(Color.fontPrimary).lineLimit(mode == .preview ? 2 : nil)
            HStack(spacing: .spacing4) {
                if let prepTime { Label(prepTime, systemImage: SFSymbol.clock).font(.omXs) }
                if let servings { Label("\(servings) servings", systemImage: SFSymbol.users).font(.omXs) }
                if let calories { Label("\(calories) kcal", systemImage: SFSymbol.zap).font(.omXs) }
            }
            .foregroundStyle(Color.fontTertiary)
        }
        .padding(.spacing4)
        .frame(maxWidth: .infinity, maxHeight: mode == .preview ? .infinity : nil, alignment: .topLeading)
    }
}

struct ShoppingProductRenderer: View {
    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode

    private var title: String { data?["title"]?.value as? String ?? "Product" }
    private var price: Double? { data?["price"]?.value as? Double }
    private var currency: String { data?["currency"]?.value as? String ?? "€" }
    private var rating: Double? { data?["rating"]?.value as? Double }
    private var seller: String? { data?["seller"]?.value as? String }
    private var imageUrl: String? { data?["image_url"]?.value as? String }

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            if let imageUrl, let imgURL = URL(string: imageUrl) {
                AsyncImage(url: imgURL) { image in
                    image.resizable().aspectRatio(contentMode: mode == .preview ? .fill : .fit)
                } placeholder: { Color.grey20 }
                .frame(height: mode == .preview ? 80 : nil)
                .clipShape(RoundedRectangle(cornerRadius: .radius2))
            }
            Text(title).font(mode == .preview ? .omXs : .omH4).fontWeight(.medium)
                .foregroundStyle(Color.fontPrimary).lineLimit(mode == .preview ? 2 : nil)
            if let price {
                Text("\(currency)\(String(format: "%.2f", price))")
                    .font(.omP).fontWeight(.bold).foregroundStyle(Color.fontPrimary)
            }
            HStack(spacing: .spacing3) {
                if let rating {
                    HStack(spacing: 2) {
                        Image(systemName: "star.fill").foregroundStyle(.yellow).font(.caption2)
                        Text(String(format: "%.1f", rating)).font(.omTiny)
                    }
                }
                if let seller { Text(seller).font(.omTiny).foregroundStyle(Color.fontTertiary) }
            }
        }
        .padding(.spacing3)
        .frame(maxWidth: .infinity, maxHeight: mode == .preview ? .infinity : nil, alignment: .topLeading)
    }
}
