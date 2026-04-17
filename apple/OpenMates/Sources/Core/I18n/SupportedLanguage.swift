// Supported language definitions — mirrors frontend/packages/ui/src/i18n/languages.json.
// 21 languages with RTL support for Arabic and Hebrew.

import Foundation

enum SupportedLanguage: String, CaseIterable, Identifiable {
    case en, de, zh, es, fr, pt, ru, ja, ko, it, tr, vi, id, pl, nl, ar, hi, th, cs, sv, he

    var id: String { rawValue }
    var code: String { rawValue }

    var name: String {
        switch self {
        case .en: return "English"
        case .de: return "Deutsch"
        case .zh: return "中文"
        case .es: return "Español"
        case .fr: return "Français"
        case .pt: return "Português"
        case .ru: return "Русский"
        case .ja: return "日本語"
        case .ko: return "한국어"
        case .it: return "Italiano"
        case .tr: return "Türkçe"
        case .vi: return "Tiếng Việt"
        case .id: return "Bahasa Indonesia"
        case .pl: return "Polski"
        case .nl: return "Nederlands"
        case .ar: return "العربية"
        case .hi: return "हिन्दी"
        case .th: return "ไทย"
        case .cs: return "Čeština"
        case .sv: return "Svenska"
        case .he: return "עברית"
        }
    }

    var shortCode: String { rawValue.uppercased() }

    var isRTL: Bool {
        self == .ar || self == .he
    }

    var layoutDirection: LayoutDirection {
        isRTL ? .rightToLeft : .leftToRight
    }

    static func from(code: String) -> SupportedLanguage? {
        SupportedLanguage(rawValue: code.lowercased())
    }

    static func fromDeviceLocale() -> SupportedLanguage {
        let preferred = Locale.preferredLanguages.first ?? "en"
        let languageCode = Locale(identifier: preferred).language.languageCode?.identifier ?? "en"
        return from(code: languageCode) ?? .en
    }
}
