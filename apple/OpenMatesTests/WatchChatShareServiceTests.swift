// Synthetic account-free encrypted sharing contract coverage. No server writes.
import CryptoKit
import Foundation
import XCTest
@testable import OpenMates

@MainActor
final class WatchChatShareServiceTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testSyntheticSharePublishesOnlyCiphertextAndRoundTripsPasswordExpiry() async throws {
        let chat = makeChat()
        let rawKey = Data(repeating: 0xfb, count: 32)
        let key = SymmetricKey(data: rawKey)
        var requests: [(String, [String: Any])] = []
        let dependencies = WatchChatShareDependencies(key: { _, _ in key }, request: { path, body, _ in
            requests.append((path, try JSONSerialization.jsonObject(with: body) as! [String: Any]))
            return Data("{\"success\":true}".utf8)
        })
        let url = try await WatchChatShareService.create(chat: chat, context: context(), duration: .tenMinutes,
                                                        password: "code+123", dependencies: dependencies)
        XCTAssertEqual(requests.map(\.0), ["/v1/share/short-url", "/v1/share/chat/metadata"])
        let short = requests[0].1
        XCTAssertEqual(short["content_type"] as? String, "chat")
        XCTAssertEqual(short["content_id"] as? String, chat.id)
        XCTAssertEqual(short["ttl_seconds"] as? Int, 600)
        XCTAssertEqual(short["password_protected"] as? Bool, true)
        XCTAssertTrue(url.path.hasPrefix("/s/"))
        XCTAssertFalse(url.absoluteString.contains("key="))
        let token = try XCTUnwrap(short["token"] as? String)
        XCTAssertEqual(url.lastPathComponent, token)
        let long = try await ShareLinkCrypto.decryptShortURL(try XCTUnwrap(short["encrypted_url"] as? String),
                                                            token: token, shortKey: try XCTUnwrap(url.fragment))
        XCTAssertEqual(long.path, "/share/chat/" + chat.id)
        let blob = try XCTUnwrap(long.fragment).replacingOccurrences(of: "key=", with: "")
        let now = Int(Date().timeIntervalSince1970)
        let recipientKey = try await SharedChatRecipientCrypto.chatKey(id: chat.id, blob: blob, serverTime: now, password: "code+123")
        XCTAssertEqual(recipientKey.withUnsafeBytes { Data($0) }, rawKey)
        do {
            _ = try await SharedChatRecipientCrypto.chatKey(id: chat.id, blob: blob, serverTime: now, password: "wrong")
            XCTFail("Protected share accepted another password")
        } catch { }
        do {
            _ = try await SharedChatRecipientCrypto.chatKey(id: chat.id, blob: blob, serverTime: now + 601, password: "code+123")
            XCTFail("Expired share accepted")
        } catch { }
        let metadata = requests[1].1
        XCTAssertEqual(metadata["share_pii"] as? Bool, false)
        XCTAssertEqual(metadata["share_highlights"] as? Bool, false)
        XCTAssertNil(metadata["share_link"])
        let stored = try XCTUnwrap(metadata["encrypted_shared_short_url"] as? String)
        let restored = try await CryptoManager.shared.decryptContent(base64String: stored, key: key)
        XCTAssertEqual(restored, url.absoluteString)
        let wire = String(decoding: try JSONSerialization.data(withJSONObject: short), as: UTF8.self)
        XCTAssertFalse(wire.contains(url.absoluteString)); XCTAssertFalse(wire.contains("code+123"))
        XCTAssertFalse(wire.contains(rawKey.base64EncodedString()))
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testRestrictionsMissingKeysAndUnavailableShortEndpointNeverExposeLongFallback() async throws {
        var publications = 0
        let dependencies = WatchChatShareDependencies(key: { _, _ in SymmetricKey(size: .bits256) }, request: { _, _, _ in
            publications += 1
            throw WatchChatShareError.publicationFailed
        })
        for chat in [restrictedChat(support: true), restrictedChat(recipient: true), restrictedChat(incognito: true)] {
            do {
                _ = try await WatchChatShareService.create(chat: chat, context: context(), duration: .noExpiration,
                                                          password: nil, dependencies: dependencies)
                XCTFail("Restricted chat shared")
            } catch { }
        }
        XCTAssertEqual(publications, 0)
        for password in ["", "12345678901"] {
            do {
                _ = try await WatchChatShareService.create(chat: makeChat(), context: context(), duration: .noExpiration,
                                                          password: password, dependencies: dependencies)
                XCTFail("Invalid password shared")
            } catch { }
        }
        XCTAssertEqual(publications, 0)
        do {
            _ = try await WatchChatShareService.create(chat: makeChat(), context: context(), duration: .noExpiration,
                                                      password: nil, dependencies: dependencies)
            XCTFail("Short endpoint failure yielded a link")
        } catch { }
        XCTAssertEqual(publications, 1)
        let missingKey = WatchChatShareDependencies(key: { _, _ in throw WatchChatShareError.unavailable }, request: dependencies.request)
        do {
            _ = try await WatchChatShareService.create(chat: makeChat(), context: context(), duration: .noExpiration,
                                                      password: nil, dependencies: missingKey)
            XCTFail("Missing key yielded a link")
        } catch { }
        XCTAssertEqual(publications, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=chat-share-settings.shared-link-open
    func testSessionRotationAfterShortCreationStopsMetadataPublication() async throws {
        var requests = 0
        let dependencies = WatchChatShareDependencies(key: { _, _ in SymmetricKey(size: .bits256) }, request: { _, _, _ in
            requests += 1
            WatchChatAccountLifecycle.invalidate()
            return Data("{\"success\":true}".utf8)
        })
        do {
            _ = try await WatchChatShareService.create(chat: makeChat(), context: context(), duration: .oneMinute,
                                                      password: nil, dependencies: dependencies)
            XCTFail("Rotated session yielded link")
        } catch is CancellationError { } catch { XCTFail("Unexpected error") }
        XCTAssertEqual(requests, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=apple-watch.chats.compact-layout
    func testHeaderMetadataDecodesEncryptedWireAndLegacySnapshot() throws {
        let wire = Data("{\"id\":\"fixture\",\"encrypted_category\":\"category-cipher\",\"encrypted_icon\":\"icon-cipher\",\"is_support_chat\":true}".utf8)
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        let dto = try decoder.decode(WatchChatDTO.self, from: wire)
        let remote = WatchRemoteChat(dto: dto)
        XCTAssertEqual(remote.encryptedCategory, "category-cipher")
        XCTAssertEqual(remote.encryptedIcon, "icon-cipher")
        XCTAssertTrue(remote.isSupportChat)
        for field in ["encrypted_category", "encryptedCategory", "encrypted_chat_category", "encryptedChatCategory"] {
            let wire = try JSONSerialization.data(withJSONObject: ["id": "fixture", field: "category-cipher"])
            for strategy in [JSONDecoder.KeyDecodingStrategy.useDefaultKeys, .convertFromSnakeCase] {
                let aliasDecoder = JSONDecoder(); aliasDecoder.keyDecodingStrategy = strategy
                XCTAssertEqual(try aliasDecoder.decode(WatchChatDTO.self, from: wire).encryptedCategory,
                               "category-cipher", "Category alias must work under either backend decoding strategy")
            }
        }
        let old = Data("{\"id\":\"old\",\"isPinned\":false}".utf8)
        let summary = try JSONDecoder().decode(WatchChatSummary.self, from: old)
        XCTAssertNil(summary.category); XCTAssertNil(summary.encryptedCategory)
        XCTAssertFalse(summary.isSupportChat); XCTAssertFalse(summary.isSharedRecipient)
    }

    private func context() -> WatchChatRequestContext {
        WatchChatRequestContext(accountID: "synthetic-account", profile: ServerProfile.current(),
                                accountGeneration: WatchChatAccountLifecycle.generation, deadline: { _ in nil })
    }
    private func makeChat() -> WatchChatSummary {
        WatchChatSummary(id: "synthetic-chat", title: "Public fixture", lastMessageAt: nil,
            preview: "Synthetic summary", isPinned: false, encryptedTitle: nil, encryptedPreview: nil, encryptedChatKey: nil)
    }
    private func restrictedChat(support: Bool = false, recipient: Bool = false, incognito: Bool = false) -> WatchChatSummary {
        var chat = makeChat()
        if incognito { chat = WatchChatSummary(id: "incognito-fixture", title: nil, lastMessageAt: nil,
            preview: nil, isPinned: false, encryptedTitle: nil, encryptedPreview: nil, encryptedChatKey: nil) }
        chat.isSupportChat = support; chat.isSharedRecipient = recipient
        return chat
    }
}
