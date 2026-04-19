// Data convenience extensions for hex string conversion and base64url encoding.
// Used throughout the crypto and passkey flows.

import Foundation
import SwiftUI

extension Data {
    init(hexString: String) {
        let hex = hexString.replacingOccurrences(of: " ", with: "")
        var data = Data(capacity: hex.count / 2)
        var index = hex.startIndex
        while index < hex.endIndex {
            let nextIndex = hex.index(index, offsetBy: 2)
            if let byte = UInt8(hex[index..<nextIndex], radix: 16) {
                data.append(byte)
            }
            index = nextIndex
        }
        self = data
    }

    func hexString() -> String {
        map { String(format: "%02x", $0) }.joined()
    }

    init?(base64URLEncoded string: String) {
        var base64 = string
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")

        let remainder = base64.count % 4
        if remainder > 0 {
            base64.append(String(repeating: "=", count: 4 - remainder))
        }

        self.init(base64Encoded: base64)
    }

    func base64URLEncodedString() -> String {
        base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}

extension Color {
    init(hex: UInt32) {
        let r = Double((hex >> 16) & 0xFF) / 255.0
        let g = Double((hex >> 8) & 0xFF) / 255.0
        let b = Double(hex & 0xFF) / 255.0
        self.init(red: r, green: g, blue: b)
    }
}

extension LinearGradient {
    /// Dark incognito gradient — matches ChatHeader.svelte's fixed incognito state:
    /// `linear-gradient(135deg, #1a1a2e 0%, #2d2d44 50%, #1e1e35 100%)`
    static let incognito = LinearGradient(
        colors: [Color(hex: 0x1A1A2E), Color(hex: 0x2D2D44), Color(hex: 0x1E1E35)],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )
}
