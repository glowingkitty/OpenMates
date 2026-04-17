// Custom font registration for Lexend Deca Variable.
// Call registerFonts() at app launch to ensure the custom font is available.
// The font file must be in the app bundle and listed in Info.plist.

import SwiftUI
import CoreText

enum FontRegistration {
    static var isRegistered = false

    static func registerFonts() {
        guard !isRegistered else { return }
        isRegistered = true

        let fontNames = ["LexendDeca-VariableFont_wght"]

        for fontName in fontNames {
            guard let url = Bundle.main.url(forResource: fontName, withExtension: "ttf")
                    ?? Bundle.main.url(forResource: fontName, withExtension: "otf") else {
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

    static var fontFamily: String {
        isRegistered ? "Lexend Deca Variable" : "SF Pro"
    }
}
