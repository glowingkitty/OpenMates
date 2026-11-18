// EmbroideryDesignModel — typed view of a design.embroidery result embed.
// Maps already-decoded embed content fields into view properties and formats the
// numbers the way the web does; no transport or crypto logic lives here.
//
// Web: frontend/packages/ui/src/components/embeds/design/embroideryDesign.ts
//      frontend/packages/ui/src/components/embeds/design/embroideryDownload.ts (file names)
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity

import Foundation

struct EmbroideryFileRef: Equatable, Sendable {
    let s3Key: String
    let aesNonce: String?
    let encryption: String?
}

struct EmbroideryThreadRow: Equatable, Sendable {
    let colourHex: String
    let name: String
    let stitchCount: Int
    let estimatedMinutes: Double?
    let threadLengthM: Double?
}

struct EmbroideryNoteRow: Equatable, Sendable {
    let code: String
    let text: String
    let count: Int?
    let mm: Int?
}

struct EmbroideryDesignModel: Equatable, Sendable {
    enum Status: String, Sendable { case processing, finished, error }
    enum FitsHoop: String, Sendable { case yes, no, notChecked = "not_checked" }

    /// Machine formats offered for download, in web order.
    static let formats = ["dst", "pes", "exp", "jef", "vp3"]
    static let hoops = ["none", "100x100", "130x180", "160x260", "200x300"]
    static let errorCodes = ["unreadable_svg", "nothing_to_sew", "too_many_stitches", "timeout", "sandbox_failed", "invalid_source"]
    private static let findings = ["gradient_or_filter", "live_text", "embedded_pixel_image", "detail_below_1mm", "more_than_12_colours"]
    static let noteCodes: Set<String> = Set(
        ["background_removed", "tiny_details_removed", "lines_running", "gradient_flattened", "effects_ignored",
         "image_left_out", "text_left_out", "rotate_for_hoop", "rework_failed", "instructions_applied", "border_added",
         "sized_to_hoop"]
            + findings.map { "solved_\($0)" } + findings.map { "unsolved_\($0)" })

    /// Fabric colour behind the stitch preview (`EMBROIDERY_FABRIC_COLOUR`).
    static let fabricColourHex = "#f4f1ea"

    let status: Status
    let title: String
    let widthMm: Double?
    let heightMm: Double?
    let stitchCount: Int?
    let threadChanges: Int?
    let estimatedMinutes: Double?
    let threadLengthM: Double?
    let hoop: String
    let fitsHoop: FitsHoop
    let fabric: String?
    let borderMm: Int
    let reworked: Bool
    let threads: [EmbroideryThreadRow]
    let notes: [EmbroideryNoteRow]
    let files: [String: EmbroideryFileRef]
    let s3BaseUrl: String
    let aesKey: String
    let aesNonce: String
    let errorCode: String?

    init(data: [String: AnyCodable]?, fallbackStatus: EmbedStatus? = nil) {
        let raw = data?.mapValues(\.value) ?? [:]
        let rawStatus = (raw["status"] as? String) ?? ""
        switch rawStatus.isEmpty ? (fallbackStatus?.rawValue ?? "") : rawStatus {
        case "processing": status = .processing
        case "error": status = .error
        default: status = .finished
        }
        title = Self.string(raw["title"])
        widthMm = Self.number(raw["width_mm"])
        heightMm = Self.number(raw["height_mm"])
        stitchCount = Self.number(raw["stitch_count"]).map { Int($0) }
        threadChanges = Self.number(raw["thread_changes"]).map { Int($0) }
        estimatedMinutes = Self.number(raw["estimated_minutes"])
        threadLengthM = Self.number(raw["thread_length_m"])
        let hoopValue = Self.string(raw["hoop"])
        hoop = Self.hoops.contains(hoopValue) ? hoopValue : "none"
        fitsHoop = FitsHoop(rawValue: Self.string(raw["fits_hoop"])) ?? .notChecked
        let fabricValue = Self.string(raw["fabric"])
        fabric = ["light", "normal", "stretchy"].contains(fabricValue) ? fabricValue : nil
        let border = Self.number(raw["border_mm"]) ?? 0
        borderMm = border > 0 ? Int(border.rounded()) : 0
        reworked = (raw["reworked"] as? Bool) == true
        threads = (raw["threads"] as? [Any] ?? []).compactMap { $0 as? [String: Any] }.map { row in
            let hex = Self.string(row["colour_hex"])
            return EmbroideryThreadRow(
                colourHex: Self.isHexColour(hex) ? hex : "",
                name: Self.string(row["name"]).isEmpty ? hex : Self.string(row["name"]),
                stitchCount: Self.number(row["stitch_count"]).map { Int($0) } ?? 0,
                estimatedMinutes: Self.number(row["estimated_minutes"]),
                threadLengthM: Self.number(row["thread_length_m"]))
        }
        notes = (raw["notes"] as? [Any] ?? []).compactMap { $0 as? [String: Any] }.map {
            EmbroideryNoteRow(code: Self.string($0["code"]), text: Self.string($0["text"]),
                              count: Self.number($0["count"]).map { Int($0) }, mm: Self.number($0["mm"]).map { Int($0) })
        }.filter { !$0.code.isEmpty || !$0.text.isEmpty }
        var parsedFiles: [String: EmbroideryFileRef] = [:]
        for (key, value) in (raw["files"] as? [String: Any] ?? [:]) {
            guard let file = value as? [String: Any], let s3 = file["s3_key"] as? String, !s3.isEmpty else { continue }
            parsedFiles[key] = EmbroideryFileRef(s3Key: s3, aesNonce: file["aes_nonce"] as? String, encryption: file["encryption"] as? String)
        }
        files = parsedFiles
        s3BaseUrl = Self.string(raw["s3_base_url"])
        aesKey = Self.string(raw["aes_key"])
        aesNonce = Self.string(raw["aes_nonce"])
        let code = Self.string(raw["error_code"])
        errorCode = Self.errorCodes.contains(code) ? code : nil
    }

    // MARK: - Derived values

    @MainActor var skillTitle: String { title.isEmpty ? AppStrings.embroiderySkillName : title }
    var showsGraphicSwitch: Bool { files["prepared_svg"] != nil }
    var hoopLabel: String { Self.formatHoop(hoop) }
    var errorKey: String { "embeds.design.embroidery.error.\(errorCode ?? "generic")" }

    /// File name stem for downloads: letters, digits and dashes only (web `downloadBaseName`).
    var downloadBaseName: String {
        let folded = title.folding(options: [.diacriticInsensitive], locale: nil).lowercased()
        var out = ""
        var lastDash = true
        for scalar in folded.unicodeScalars {
            if scalar.isASCII, CharacterSet.alphanumerics.contains(scalar) { out.unicodeScalars.append(scalar); lastDash = false }
            else if !lastDash { out.append("-"); lastDash = true }
        }
        var stem = String(out.trimmingCharacters(in: CharacterSet(charactersIn: "-")).prefix(48))
        while stem.hasSuffix("-") { stem.removeLast() }
        return stem.isEmpty ? "embroidery-design" : stem
    }

    func file(_ key: String) -> EmbroideryFileRef? { files[key] }

    /// Nonce for a file: its own, else the content-level legacy nonce.
    func nonce(for file: EmbroideryFileRef) -> String? {
        if let own = file.aesNonce, !own.isEmpty { return own }
        return aesNonce.isEmpty ? nil : aesNonce
    }

    /// Whether the file carries enough metadata to be decrypted.
    func canDecrypt(_ file: EmbroideryFileRef) -> Bool {
        !aesKey.isEmpty && (nonce(for: file) != nil || file.encryption == S3MediaClient.noncePrefixedEncryption)
    }

    // MARK: - Formatting (embroideryDesign.ts)

    /// "100x100" becomes "100 × 100 mm"; "none" is empty.
    static func formatHoop(_ hoop: String) -> String {
        hoop == "none" ? "" : "\(hoop.replacingOccurrences(of: "x", with: " × ")) mm"
    }

    static func formatSize(width: Double?, height: Double?) -> String {
        guard let width, let height else { return "" }
        return "\(Int(width.rounded())) × \(Int(height.rounded())) mm"
    }

    var sizeLabel: String { Self.formatSize(width: widthMm, height: heightMm) }

    static func formatCount(_ value: Int?) -> String {
        value.map { $0.formatted() } ?? ""
    }

    /// "47 min" or "1 h 5 min".
    static func formatDuration(_ minutes: Double?) -> String {
        guard let minutes else { return "" }
        let whole = max(1, Int(minutes.rounded()))
        return whole < 60 ? "\(whole) min" : "\(whole / 60) h \(whole % 60) min"
    }

    /// "80 cm", "4.5 m" or "62 m".
    static func formatThreadLength(_ metres: Double?) -> String {
        guard let metres else { return "" }
        if metres < 1 { return "\(max(10, Int((metres * 100).rounded()))) cm" }
        if metres < 10 { return "\((metres * 10).rounded() / 10) m".replacingOccurrences(of: ".0 m", with: " m") }
        return "\(Int(metres.rounded()).formatted()) m"
    }

    static func noteKey(_ code: String) -> String? {
        noteCodes.contains(code) ? "embeds.design.embroidery.note.\(code)" : nil
    }

    // MARK: - Decoding helpers

    private static func string(_ value: Any?) -> String { value as? String ?? "" }

    private static func number(_ value: Any?) -> Double? {
        if value is Bool { return nil }
        if let double = value as? Double { return double.isFinite ? double : nil }
        if let int = value as? Int { return Double(int) }
        if let number = value as? NSNumber { return number.doubleValue.isFinite ? number.doubleValue : nil }
        return nil
    }

    static func isHexColour(_ value: String) -> Bool {
        guard value.hasPrefix("#"), (4...9).contains(value.count) else { return false }
        return value.dropFirst().allSatisfy { $0.isHexDigit }
    }
}
