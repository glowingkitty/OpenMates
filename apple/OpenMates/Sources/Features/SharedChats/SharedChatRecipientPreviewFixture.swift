// Synthetic native launch fixtures corresponding to SharedChatRecipientPreviewHarness.
// No real accounts, keys, URLs, network requests or owner cache writes.
// Web: frontend/packages/ui/src/components/chats/SharedChatRecipientPreviewHarness.svelte
// Specification: specifications/features/chat-share-settings/specification.yml
// Assertions: chat-share-settings.shared-link-open, chat-share-settings.readonly-viewer-controls

#if DEBUG
import CryptoKit
import Foundation
import SwiftUI

@MainActor
enum SharedChatRecipientPreviewFixture {
    static let url = URL(string: "https://openmates.org/share/chat/recipient-preview#key=synthetic-preview-ciphertext")!

    static func model(state: String) -> SharedChatRecipientModel {
        switch state {
        case "ready", "target", "embed", "imageSiblings":
            return .init(previewState: .ready, previewContext: context(target: state == "target", includeEmbed: state == "embed", includeImageSiblings: state == "imageSiblings"))
        case "password": return .init(previewState: .passwordRequired)
        case "invalidPassword": return .init(previewState: .failed(.invalidPassword))
        case "error", "unavailable": return .init(previewState: .failed(.unavailable))
        default: return .init(previewState: .loading)
        }
    }

    static func context(target: Bool = false, includeEmbed: Bool = false, includeImageSiblings: Bool = false) -> SharedChatRecipientContext {
        let timestamp = "2026-09-08T16:00:00Z"
        let chat = Chat(id: "recipient-preview", title: "Launch preparation", lastMessageAt: nil,
                        createdAt: timestamp, updatedAt: timestamp, isArchived: false, isPinned: false,
                        appId: nil, category: "general_knowledge", chatSummary: "Coordinate the work and verify the outcome before completion.",
                        encryptedTitle: nil, encryptedChatKey: nil)
        let code = EmbedRecord(id: "recipient-file", type: "code-code", status: .finished,
                               data: .raw(["code": AnyCodable("print('Synthetic file')"), "language": AnyCodable("python"),
                                           "filename": AnyCodable("verification.py")]),
                               parentEmbedId: nil, appId: "code", skillId: nil, embedIds: nil, createdAt: timestamp)
        let imageRecords = includeImageSiblings ? syntheticImageRecords(timestamp: timestamp) : []
        let displayedEmbed = includeImageSiblings ? imageRecords.first : includeEmbed ? code : nil
        let embedContent = displayedEmbed.map { "```json\n{\"type\":\"\($0.type)\",\"embed_id\":\"\($0.id)\",\"status\":\"finished\"}\n```" }
        var messages = [
            Message(id: "recipient-user", chatId: chat.id, role: .user,
                    content: "What should we verify before release?", encryptedContent: nil,
                    createdAt: timestamp, updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil),
            Message(id: "recipient-assistant", chatId: chat.id, role: .assistant,
                    content: embedContent ?? "Verify the result and review the evidence before completion.", encryptedContent: nil,
                    createdAt: timestamp, updatedAt: nil, appId: nil, isStreaming: false,
                    embedRefs: displayedEmbed.map { [EmbedRef(id: $0.id, type: $0.type, status: "finished", data: nil)] },
                    senderName: "Sophia", category: "general_knowledge")
        ]
        if target {
            messages += (0..<24).map { index in
                Message(id: "recipient-history-\(index)", chatId: chat.id, role: index.isMultiple(of: 2) ? .user : .assistant,
                        content: "Synthetic history message \(index + 1).", encryptedContent: nil,
                        createdAt: timestamp, updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil)
            }
            messages.append(Message(id: "recipient-target", chatId: chat.id, role: .user,
                                    content: "Synthetic target message.", encryptedContent: nil,
                                    createdAt: timestamp, updatedAt: nil, appId: nil, isStreaming: false, embedRefs: nil))
        }
        let chatKey = SymmetricKey(data: Data(repeating: 7, count: 32))
        let rowKey = SymmetricKey(data: Data(repeating: 8, count: 32))
        func encrypt(_ text: String) -> String { (try? ComposerEmbedCrypto.encryptContent(text, using: rowKey)) ?? "" }
        func hash(_ value: String) -> String { SHA256.hash(data: Data(value.utf8)).map { String(format: "%02x", $0) }.joined() }
        let wrapper = (try? ComposerEmbedCrypto.wrapKey(rowKey, using: chatKey)) ?? ""
        let manifest: [String: Any] = [
            "chat_id": chat.id,
            "tasks": [["task_id": "recipient-task", "status": "todo", "encrypted_title": encrypt("Review the release checklist"),
                       "encrypted_description": encrypt("Verify the outcome before completion.")]],
            "task_key_wrappers": [["key_type": "chat", "hashed_task_id": hash("recipient-task"), "encrypted_task_key": wrapper]],
            "plans": [["plan_id": "recipient-plan", "status": "active", "encrypted_title": encrypt("Prepare the launch"),
                       "encrypted_goal": encrypt("Coordinate the work and verify the outcome.")]],
            "plan_key_wrappers": [["key_type": "chat", "hashed_plan_id": hash("recipient-plan"), "encrypted_plan_key": wrapper]]
        ]
        return .init(originalURL: url, resolvedURL: url, chatKey: chatKey, chat: chat,
                     messages: messages, embeds: Dictionary(uniqueKeysWithValues: ([code] + imageRecords).map { ($0.id, $0) }),
                     encryptedManifest: (try? JSONSerialization.data(withJSONObject: manifest)) ?? Data(),
                     targetMessageID: target ? "recipient-target" : nil,
                     sharePII: false, shareHighlights: false, hasMoreBefore: false,
                     nextBeforeTimestamp: nil, nextBeforeMessageID: nil)
    }

    // Fixed 2×2 RGBA PNGs contain only solid red/blue pixels. AES material is
    // synthetic, and the injected loader has no URLSession/network fallback.
    static let imagePNGs = [
        Data(base64Encoded: "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAEUlEQVR4nGP4z8DwH4QZYAwAR8oH+WdZbrcAAAAASUVORK5CYII=")!,
        Data(base64Encoded: "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAEElEQVR4nGNgYPj/H4KhDAA/0gf5tBJPzQAAAABJRU5ErkJggg==")!
    ]
    static let imageURLs = [URL(string: "https://example.invalid/recipient-red.png")!, URL(string: "https://example.invalid/recipient-blue.png")!]
    private static let imageKey = Data(repeating: 9, count: 32)

    private static func syntheticImageRecords(timestamp: String) -> [EmbedRecord] {
        imageURLs.enumerated().map { index, url in
            EmbedRecord(id: index == 0 ? "recipient-image-a" : "recipient-image-b", type: "image", status: .finished,
                        data: .raw(["s3_url": AnyCodable(url.absoluteString), "aes_key": AnyCodable(imageKey.map { String(format: "%02x", $0) }.joined()),
                                    "encryption": AnyCodable(S3MediaClient.noncePrefixedEncryption),
                                    "filename": AnyCodable(index == 0 ? "Synthetic red.png" : "Synthetic blue.png")]),
                        parentEmbedId: nil, appId: "images", skillId: nil, embedIds: nil, createdAt: timestamp)
        }
    }

    static func imageRequestLoader() throws -> RecipientMediaTransport.RequestLoader {
        let key = SymmetricKey(data: imageKey)
        let encrypted = try imagePNGs.enumerated().map { index, bytes in
            let nonce = try AES.GCM.Nonce(data: Data(repeating: UInt8(11 + index), count: 12))
            return try AES.GCM.seal(bytes, using: key, nonce: nonce).combined!
        }
        let responses = Dictionary(uniqueKeysWithValues: zip(imageURLs, encrypted))
        return { request in
            guard request.httpMethod == "GET", let url = request.url, let data = responses[url],
                  let response = HTTPURLResponse(url: url, statusCode: 200, httpVersion: nil, headerFields: ["Content-Type": "application/octet-stream"]) else {
                throw URLError(.resourceUnavailable)
            }
            return (data, response)
        }
    }
}

extension SharedChatRecipientView {
    static func preview(state: String = "ready") -> SharedChatRecipientView {
        .init(url: SharedChatRecipientPreviewFixture.url,
              model: SharedChatRecipientPreviewFixture.model(state: state), onPasswordSubmit: { _ in },
              recipientMediaRequestLoader: state == "imageSiblings" ? (try? SharedChatRecipientPreviewFixture.imageRequestLoader()) : nil)
    }
}
#endif
