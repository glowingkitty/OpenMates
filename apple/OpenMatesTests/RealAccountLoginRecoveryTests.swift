// Explicit live-dev diagnostic for native password unlock. Uses the same local,
// ignored credential file as XCUITest; never logs credentials or response bodies.
import XCTest
import CryptoKit
@testable import OpenMates

@MainActor
final class RealAccountLoginRecoveryTests: XCTestCase {
    // contract-test: direct surface=gui.apple assertions=auth.login.method-convergence,auth.session.lifecycle
    func testPersonalDevPasswordUnlocksSessionAndLoadsCompleteMetadata() async throws {
        guard ServerProfile.current() == .development else {
            throw XCTSkip("Live recovery test requires the development server")
        }
        let file = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent(".openmates-live-test-account.env")
        guard let text = try? String(contentsOf: file, encoding: .utf8) else {
            throw XCTSkip("Local live test credentials are unavailable")
        }
        let values = Dictionary(uniqueKeysWithValues: text.split(separator: "\n").compactMap { line -> (String, String)? in
            let parts = line.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
            return parts.count == 2 ? (String(parts[0]), String(parts[1])) : nil
        })
        let email = try XCTUnwrap(values["OPENMATES_TEST_ACCOUNT_EMAIL"])
        let password = try XCTUnwrap(values["OPENMATES_TEST_ACCOUNT_PASSWORD"])
        let auth = AuthManager()
        let lookup = try await auth.lookup(email: email)
        do {
            try await auth.loginWithPassword(email: email, password: password, userEmailSalt: lookup.userEmailSalt)
        } catch AuthError.tfaRequired {
            let otpKey = try XCTUnwrap(values["OPENMATES_TEST_ACCOUNT_OTP_KEY"])
            try await auth.loginWithPassword(email: email, password: password,
                                             userEmailSalt: lookup.userEmailSalt,
                                             tfaCode: RecoveryTOTP.generate(secret: otpKey))
        }
        XCTAssertEqual(auth.state, .authenticated)
        XCTAssertNotNil(auth.currentUser)
        XCTAssertNotNil(OfflineStore.shared.activeScopeId)

        // Exercise the real server pagination contract without UI scrolling cost.
        let socket = WebSocketManager()
        socket.connect(sessionId: AuthManager.nativeSessionId, token: nil)
        defer { socket.disconnect() }
        let deadline = Date().addingTimeInterval(20)
        while !socket.isConnected && Date() < deadline {
            try await Task.sleep(for: .milliseconds(100))
        }
        XCTAssertTrue(socket.isConnected)
        var offset = 0
        var ids = Set<String>()
        var total = 0
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        repeat {
            let requestedOffset = offset
            let response = try await socket.sendAndWait(
                WSOutboundMessage(type: "load_more_chats", payload: ["offset": offset, "limit": 50, "context_epoch": 0]),
                responseType: "load_more_chats_response",
                matching: { ($0["offset"] as? Int) == requestedOffset }
            )
            let page = try decoder.decode(ChatMetadataPage.self,
                from: JSONSerialization.data(withJSONObject: response.fields))
            XCTAssertNil(page.error)
            let chats = (page.chats ?? []).compactMap(\.chatDetails)
            total = try XCTUnwrap(page.totalCount)
            for chat in chats { XCTAssertTrue(ids.insert(chat.id).inserted, "Server pagination repeated a chat") }
            offset += chats.count
            if page.hasMore != true { break }
            XCTAssertFalse(chats.isEmpty, "Server pagination stopped progressing")
            guard !chats.isEmpty, offset < 10_000 else { break }
        } while true
        XCTAssertEqual(ids.count, total, "Native pagination must reach the complete server chat list")
        print("[Recovery] unique metadata count=\(ids.count) serverTotal=\(total)")
    }
}

// Same RFC 6238 fixture used by the live UI workflow; no code or secret is logged.
private enum RecoveryTOTP {
    static func generate(secret: String, windowOffset: Int = 0, date: Date = Date()) -> String {
        let key = SymmetricKey(data: base32Decode(secret))
        let counter = UInt64(Int64(floor(date.timeIntervalSince1970 / 30.0)) + Int64(windowOffset))
        var counterBigEndian = counter.bigEndian
        let counterData = Data(bytes: &counterBigEndian, count: MemoryLayout<UInt64>.size)
        let hash = HMAC<Insecure.SHA1>.authenticationCode(for: counterData, using: key)
        let bytes = Array(hash)
        let offset = Int(bytes[19] & 0x0f)
        let code = (UInt32(bytes[offset] & 0x7f) << 24)
            | (UInt32(bytes[offset + 1]) << 16)
            | (UInt32(bytes[offset + 2]) << 8)
            | UInt32(bytes[offset + 3])
        return String(format: "%06u", code % 1_000_000)
    }

    private static func base32Decode(_ value: String) -> Data {
        let alphabet = Array("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
        let lookup = Dictionary(uniqueKeysWithValues: alphabet.enumerated().map { ($1, $0) })
        var bits = 0
        var bitBuffer = 0
        var output = Data()

        for character in value.uppercased() where character != "=" && character != " " {
            guard let index = lookup[character] else { continue }
            bitBuffer = (bitBuffer << 5) | index
            bits += 5
            if bits >= 8 {
                bits -= 8
                output.append(UInt8((bitBuffer >> bits) & 0xff))
            }
        }

        return output
    }
}
