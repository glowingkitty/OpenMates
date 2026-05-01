// Custom font registration for Lexend Deca static weights.
// Call registerFonts() at app launch to ensure the custom font is available.
// The font files must be in the app bundle and listed in Info.plist UIAppFonts.

import SwiftUI
import CoreText

enum FontRegistration {
    nonisolated(unsafe) static var isRegistered = false

    private static let fontFiles = [
        "LexendDeca-Light",
        "LexendDeca-Regular",
        "LexendDeca-Medium",
        "LexendDeca-SemiBold",
        "LexendDeca-Bold",
        "LexendDeca-ExtraBold",
    ]

    static func registerFonts() {
        guard !isRegistered else { return }
        isRegistered = true

        for fontName in fontFiles {
            guard let url = Bundle.main.url(forResource: fontName, withExtension: "ttf") else {
                print("[Font] Font file not found: \(fontName) — using system font fallback")
                continue
            }

            var error: Unmanaged<CFError>?
            if !CTFontManagerRegisterFontsForURL(url as CFURL, .process, &error) {
                if let error = error?.takeRetainedValue() {
                    print("[Font] Registration failed for \(fontName): \(error)")
                }
            }
        }
    }

    /// The family name used by Font.custom() — matches the font's nameID=1.
    static var fontFamily: String {
        isRegistered ? "Lexend Deca" : "SF Pro"
    }
}
