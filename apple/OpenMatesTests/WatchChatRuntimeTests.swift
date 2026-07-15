// Unit coverage for the portable Watch chat runtime and offline cache.
// These tests avoid network, credentials, and message plaintext from real users.
// They lock down deterministic cache persistence, offline fallback behavior, and
// local pending message snapshots before watchOS UI tests exercise the shell.

import XCTest
import CryptoKit
@testable import OpenMates

@MainActor
final class WatchChatRuntimeTests: XCTestCase {
    func testLiveReservedAccountLoginLoadsAndOpensWatchChat() async throws {
        let credentials = try WatchLiveAccountCredentials.fromEnvironment(preferredReservedSlot: 14)
        ServerConfiguration.current = ServerProfile.development.endpointConfiguration

        let authManager = AuthManager()
        let lookup = try await authManager.lookup(email: credentials.email, stayLoggedIn: true)
        do {
            try await authManager.loginWithPassword(
                email: credentials.email,
                password: credentials.password,
                userEmailSalt: lookup.userEmailSalt,
                stayLoggedIn: true
            )
        } catch AuthError.tfaRequired {
            try await authManager.loginWithPassword(
                email: credentials.email,
                password: credentials.password,
                userEmailSalt: lookup.userEmailSalt,
                tfaCode: WatchLiveTOTP.generate(secret: credentials.otpKey),
                codeType: "otp",
                stayLoggedIn: true
            )
        }

        XCTAssertEqual(authManager.state, .authenticated)
        let loggedInUser = try XCTUnwrap(authManager.currentUser)
        let masterKey = try await CryptoManager.shared.loadMasterKey(for: loggedInUser.id)
        XCTAssertNotNil(masterKey)

        let watchSession: SessionResponse = try await APIClient.shared.request(
            .post,
            path: "/v1/auth/session",
            body: SessionRequest(
                sessionId: WatchCompatibleSession.nativeSessionId,
                deviceInfo: WatchCompatibleSession.makeNativeDeviceInfo()
            )
        )
        XCTAssertTrue(watchSession.isAuthenticated)
        XCTAssertEqual(watchSession.user?.id, loggedInUser.id)

        let runtime = WatchChatRuntime(
            currentUserId: loggedInUser.id,
            syncSocket: nil,
            syncSession: nil
        )
        await runtime.refresh()

        XCTAssertFalse(runtime.isOffline, runtime.errorMessage ?? "Watch chat refresh unexpectedly went offline")
        XCTAssertFalse(runtime.chats.isEmpty, "Real Apple test account must keep at least one decryptable saved chat for Watch smoke coverage")

        var openedMessageCount = 0
        for chat in runtime.chats.prefix(5) {
            await runtime.openChat(chat)
            XCTAssertEqual(runtime.selectedChatId, chat.id)
            if !runtime.selectedMessages.isEmpty {
                openedMessageCount = runtime.selectedMessages.count
                break
            }
        }

        XCTAssertGreaterThan(openedMessageCount, 0, "Opening a Watch chat must load at least one message from the real account")
        XCTAssertFalse(runtime.isOffline, runtime.errorMessage ?? "Watch chat open unexpectedly went offline")
    }

    func testWatchCryptoCanOmitHiddenChatCandidates() throws {
        let appleRoot = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
        let runtimeURL = appleRoot.appendingPathComponent("OpenMates/Sources/Core/Watch/WatchChatRuntime.swift")
        let source = try String(contentsOf: runtimeURL, encoding: .utf8)

        XCTAssertTrue(source.contains("func decryptChat(_ chat: WatchRemoteChat) async -> WatchChatSummary?"))
        XCTAssertTrue(source.contains("if let decrypted = await crypto.decryptChat(chat)"))
    }

    func testOfflineCacheRoundTripsSnapshot() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let snapshot = WatchChatSnapshot(
            chats: [Self.chat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")],
            messagesByChatId: ["chat-a": [Self.message(id: "msg-a", chatId: "chat-a", content: "Cached")]],
            pendingTextSends: [],
            savedAt: Date(timeIntervalSince1970: 1_783_337_600)
        )

        try await cache.saveSnapshot(snapshot)
        let loaded = await cache.loadSnapshot()

        XCTAssertEqual(loaded, snapshot)
    }

    func testRefreshFetchesChatsAndPersistsSortedSnapshot() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let api = FakeWatchChatAPI(
            chats: [
                Self.remoteChat(id: "older", title: "Older", lastMessageAt: "2026-07-05T10:00:00Z"),
                Self.remoteChat(id: "pinned", title: "Pinned", lastMessageAt: "2026-07-01T10:00:00Z", isPinned: true),
            ]
        )
        let runtime = WatchChatRuntime(api: api, cache: cache, crypto: FakeWatchChatCrypto())

        await runtime.refresh()

        XCTAssertEqual(runtime.chats.map(\.id), ["pinned", "older"])
        XCTAssertEqual(runtime.selectedChatId, "pinned")
        let cached = await cache.loadSnapshot()
        XCTAssertEqual(cached.chats.map(\.id), ["pinned", "older"])
    }

    func testRefreshExcludesChatsThatNormalMasterKeyCannotDecrypt() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let runtime = WatchChatRuntime(
            api: FakeWatchChatAPI(chats: [
                Self.remoteChat(id: "visible", title: "Visible", lastMessageAt: "2026-07-06T10:00:00Z"),
                Self.remoteChat(id: "hidden", title: nil, lastMessageAt: "2026-07-06T11:00:00Z"),
            ]),
            cache: WatchChatOfflineCache(directory: directory),
            crypto: FakeWatchChatCrypto(omittedChatIds: ["hidden"])
        )

        await runtime.refresh()

        XCTAssertEqual(runtime.chats.map(\.id), ["visible"])
    }

    func testRefreshFallsBackToCachedChatsWhenAPIThrows() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        try await cache.saveSnapshot(
            WatchChatSnapshot(
                chats: [Self.chat(id: "cached", title: "Cached", lastMessageAt: "2026-07-06T10:00:00Z")],
                messagesByChatId: [:],
                pendingTextSends: [],
                savedAt: Date()
            )
        )
        let runtime = WatchChatRuntime(api: FakeWatchChatAPI(shouldThrow: true), cache: cache, crypto: FakeWatchChatCrypto())

        await runtime.refresh()

        XCTAssertTrue(runtime.isOffline)
        XCTAssertEqual(runtime.chats.map(\.id), ["cached"])
    }

    func testOpenChatLoadsMessagesAndQueuedLocalTextPersists() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let chat = Self.chat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")
        let api = FakeWatchChatAPI(
            chats: [Self.remoteChat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")],
            messagesByChatId: [
                "chat-a": [Self.remoteMessage(id: "msg-a", chatId: "chat-a", content: "Remote")]
            ],
            shouldThrowOnSend: true
        )
        let runtime = WatchChatRuntime(api: api, cache: cache, crypto: FakeWatchChatCrypto())

        await runtime.refresh()
        await runtime.openChat(chat)
        await runtime.queueLocalText("  Pending reply  ")

        XCTAssertEqual(runtime.selectedMessages.map(\.content), ["Remote", "Pending reply"])
        XCTAssertEqual(runtime.selectedMessages.last?.isPending, true)
        let cached = await cache.loadSnapshot()
        XCTAssertEqual(cached.messagesByChatId["chat-a"]?.last?.content, "Pending reply")
        XCTAssertEqual(cached.pendingTextSends.count, 1)
    }

    func testQueuedLocalTextReplaysAndClearsPendingSnapshotWhenOnline() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let chat = Self.chat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")
        let api = FakeWatchChatAPI(
            chats: [Self.remoteChat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")],
            messagesByChatId: ["chat-a": []]
        )
        let runtime = WatchChatRuntime(api: api, cache: cache, crypto: FakeWatchChatCrypto())

        await runtime.refresh()
        await runtime.openChat(chat)
        await runtime.queueLocalText("Replay me")

        XCTAssertEqual(api.sentMessages.count, 1)
        XCTAssertEqual(runtime.selectedMessages.last?.isPending, false)
        let cached = await cache.loadSnapshot()
        XCTAssertEqual(cached.pendingTextSends.count, 0)
    }

    func testEncryptedRemoteFieldsAreDecryptedBeforeDisplay() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let api = FakeWatchChatAPI(
            chats: [
                Self.remoteChat(
                    id: "chat-a",
                    title: nil,
                    lastMessageAt: "2026-07-06T10:00:00Z",
                    encryptedTitle: "enc-title",
                    encryptedSummary: "enc-summary"
                )
            ],
            messagesByChatId: [
                "chat-a": [Self.remoteMessage(id: "msg-a", chatId: "chat-a", content: nil, encryptedContent: "enc-message")]
            ]
        )
        let crypto = FakeWatchChatCrypto(decryptedValues: [
            "enc-title": "Decrypted title",
            "enc-summary": "Decrypted summary",
            "enc-message": "Decrypted message",
        ])
        let runtime = WatchChatRuntime(api: api, cache: cache, crypto: crypto)

        await runtime.refresh()
        guard let chat = runtime.chats.first else {
            XCTFail("Expected decrypted chat")
            return
        }
        await runtime.openChat(chat)

        XCTAssertEqual(runtime.chats.first?.title, "Decrypted title")
        XCTAssertEqual(runtime.chats.first?.preview, "Decrypted summary")
        XCTAssertEqual(runtime.selectedMessages.first?.content, "Decrypted message")
    }

    func testRealtimeSyncUsesCachedWatchClientStateWithoutIncognitoChats() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let socket = FakeWatchChatSyncSocket()
        try await cache.saveSnapshot(
            WatchChatSnapshot(
                chats: [
                    Self.chat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z"),
                    Self.chat(id: "incognito-local", title: "Private", lastMessageAt: "2026-07-06T11:00:00Z"),
                ],
                messagesByChatId: [:],
                pendingTextSends: [],
                savedAt: Date()
            )
        )
        let runtime = WatchChatRuntime(
            api: FakeWatchChatAPI(),
            cache: cache,
            crypto: FakeWatchChatCrypto(),
            syncSocket: socket,
            syncSession: WatchSyncSession(sessionId: "watch-session", token: "watch-ws-token")
        )

        await runtime.loadCachedSnapshot()
        await runtime.startRealtimeSync()

        XCTAssertEqual(socket.connectedSession, WatchSyncSession(sessionId: "watch-session", token: "watch-ws-token"))
        XCTAssertEqual(socket.connectedSyncState?.clientChatIds, ["chat-a"])
        XCTAssertEqual(socket.connectedSyncState?.clientChatVersions, [:])
        XCTAssertEqual(socket.connectedSyncState?.clientEmbedIds, [])
    }

    func testAudioRecordingCreatesPendingEmbedWithoutSendingMessage() async throws {
        let directory = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: directory) }
        let cache = WatchChatOfflineCache(directory: directory)
        let chat = Self.chat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")
        let api = FakeWatchChatAPI(
            chats: [Self.remoteChat(id: "chat-a", title: "Alpha", lastMessageAt: "2026-07-06T10:00:00Z")],
            messagesByChatId: ["chat-a": []],
            uploadedAudio: Self.uploadedAudio()
        )
        let runtime = WatchChatRuntime(api: api, cache: cache, crypto: FakeWatchChatCrypto())

        await runtime.refresh()
        await runtime.openChat(chat)
        let transcript = await runtime.prepareAudioRecording(
            data: Data([0, 1, 2, 3]),
            filename: "watch-recording.m4a",
            duration: 4.2
        )

        XCTAssertEqual(transcript, "Watch transcript")
        XCTAssertEqual(api.uploadedAudioRequests.first?.chatId, "chat-a")
        XCTAssertEqual(api.transcribedAudioIds, ["watch-audio-embed"])
        XCTAssertEqual(api.sentMessages.count, 0)
        XCTAssertEqual(runtime.pendingAudioEmbeds.count, 1)
        XCTAssertEqual(runtime.pendingAudioEmbeds.first?.markdownReference, "```json\n{\"type\": \"audio-recording\", \"embed_id\": \"watch-audio-embed\"}\n```")
        XCTAssertTrue(runtime.pendingAudioEmbeds.first?.content.contains("Watch transcript") == true)
        let cached = await cache.loadSnapshot()
        XCTAssertEqual(cached.pendingAudioEmbeds.first?.id, "watch-audio-embed")
    }

    private func temporaryDirectory() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("watch-chat-runtime-tests-\(UUID().uuidString)", isDirectory: true)
    }

    private static func chat(
        id: String,
        title: String,
        lastMessageAt: String,
        isPinned: Bool = false
    ) -> WatchChatSummary {
        WatchChatSummary(
            id: id,
            title: title,
            lastMessageAt: lastMessageAt,
            preview: nil,
            isPinned: isPinned,
            encryptedTitle: nil,
            encryptedPreview: nil,
            encryptedChatKey: "wrapped-chat-key"
        )
    }

    private static func message(id: String, chatId: String, content: String) -> WatchChatMessage {
        WatchChatMessage(
            id: id,
            chatId: chatId,
            role: .assistant,
            content: content,
            encryptedContent: nil,
            createdAt: "2026-07-06T10:00:00Z",
            isPending: false
        )
    }

    private static func remoteChat(
        id: String,
        title: String?,
        lastMessageAt: String,
        isPinned: Bool = false,
        encryptedTitle: String? = nil,
        encryptedSummary: String? = nil
    ) -> WatchRemoteChat {
        WatchRemoteChat(
            id: id,
            title: title,
            lastMessageAt: lastMessageAt,
            updatedAt: nil,
            chatSummary: nil,
            isPinned: isPinned,
            encryptedTitle: encryptedTitle,
            encryptedChatSummary: encryptedSummary,
            encryptedChatKey: "wrapped-chat-key"
        )
    }

    private static func remoteMessage(
        id: String,
        chatId: String,
        content: String?,
        encryptedContent: String? = nil
    ) -> WatchRemoteMessage {
        WatchRemoteMessage(
            id: id,
            chatId: chatId,
            role: .assistant,
            content: content,
            encryptedContent: encryptedContent,
            createdAt: "2026-07-06T10:00:00Z"
        )
    }

    private static func uploadedAudio() -> WatchUploadedAudio {
        WatchUploadedAudio(
            embedId: "watch-audio-embed",
            filename: "watch-recording.m4a",
            contentType: "audio/mp4",
            contentHash: "audio-hash",
            files: [
                "original": WatchUploadedFileVariant(
                    s3Key: "recordings/watch-recording.m4a",
                    sizeBytes: 4,
                    width: nil,
                    height: nil,
                    format: "m4a"
                )
            ],
            s3BaseUrl: "https://files.example.invalid",
            aesKey: "redacted-aes-key",
            aesNonce: "redacted-aes-nonce",
            vaultWrappedAesKey: "redacted-wrapped-key"
        )
    }
}

private struct FakeAudioUploadRequest: Equatable {
    let data: Data
    let filename: String
    let chatId: String
}

private final class FakeWatchChatAPI: WatchChatAPI, @unchecked Sendable {
    private let shouldThrow: Bool
    private let shouldThrowOnSend: Bool
    private let chats: [WatchRemoteChat]
    private let messagesByChatId: [String: [WatchRemoteMessage]]
    private let uploadedAudio: WatchUploadedAudio?
    private(set) var sentMessages: [WatchPendingTextSend] = []
    private(set) var uploadedAudioRequests: [FakeAudioUploadRequest] = []
    private(set) var transcribedAudioIds: [String] = []

    init(
        chats: [WatchRemoteChat] = [],
        messagesByChatId: [String: [WatchRemoteMessage]] = [:],
        shouldThrow: Bool = false,
        shouldThrowOnSend: Bool = false,
        uploadedAudio: WatchUploadedAudio? = nil
    ) {
        self.chats = chats
        self.messagesByChatId = messagesByChatId
        self.shouldThrow = shouldThrow
        self.shouldThrowOnSend = shouldThrowOnSend
        self.uploadedAudio = uploadedAudio
    }

    func fetchRecentChats(limit: Int) async throws -> [WatchRemoteChat] {
        if shouldThrow { throw URLError(.notConnectedToInternet) }
        return Array(chats.prefix(limit))
    }

    func fetchMessages(chatId: String) async throws -> [WatchRemoteMessage] {
        if shouldThrow { throw URLError(.notConnectedToInternet) }
        return messagesByChatId[chatId] ?? []
    }

    func sendPendingText(_ pending: WatchPendingTextSend) async throws {
        if shouldThrow || shouldThrowOnSend { throw URLError(.notConnectedToInternet) }
        sentMessages.append(pending)
    }

    func uploadAudioRecording(data: Data, filename: String, chatId: String) async throws -> WatchUploadedAudio {
        if shouldThrow { throw URLError(.notConnectedToInternet) }
        uploadedAudioRequests.append(FakeAudioUploadRequest(data: data, filename: filename, chatId: chatId))
        guard let uploadedAudio else { throw WatchChatRuntimeError.audioUploadFailed }
        return uploadedAudio
    }

    func transcribeAudioRecording(_ upload: WatchUploadedAudio, chatId: String) async throws -> String? {
        if shouldThrow { throw URLError(.notConnectedToInternet) }
        transcribedAudioIds.append(upload.embedId)
        return "Watch transcript"
    }
}

private struct WatchLiveAccountCredentials {
    let email: String
    let password: String
    let otpKey: String

    static func fromEnvironment(preferredReservedSlot slot: Int) throws -> WatchLiveAccountCredentials {
        let environment = ProcessInfo.processInfo.environment
        if let credentials = read(environment: environment, prefix: "OPENMATES_TEST_ACCOUNT") {
            return credentials
        }
        if let credentials = read(environment: environment, prefix: "OPENMATES_TEST_ACCOUNT_\(slot)") {
            return credentials
        }
        let fileEnvironment = readCredentialFile()
        if let credentials = read(environment: fileEnvironment, prefix: "OPENMATES_TEST_ACCOUNT") {
            return credentials
        }
        if let credentials = read(environment: fileEnvironment, prefix: "OPENMATES_TEST_ACCOUNT_\(slot)") {
            return credentials
        }
        throw XCTSkip("Missing OPENMATES_TEST_ACCOUNT or reserved Apple slot \(slot) credentials")
    }

    private static func read(environment: [String: String], prefix: String) -> WatchLiveAccountCredentials? {
        guard let email = environment["\(prefix)_EMAIL"], !email.isEmpty,
              let password = environment["\(prefix)_PASSWORD"], !password.isEmpty,
              let otpKey = environment["\(prefix)_OTP_KEY"], !otpKey.isEmpty else {
            return nil
        }
        return WatchLiveAccountCredentials(email: email, password: password, otpKey: otpKey)
    }

    private static func readCredentialFile() -> [String: String] {
        let sourceFileURL = URL(fileURLWithPath: #filePath)
        let credentialFileURL = sourceFileURL
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .appendingPathComponent(".openmates-live-test-account.env")
        guard let contents = try? String(contentsOf: credentialFileURL, encoding: .utf8) else {
            return [:]
        }

        var values: [String: String] = [:]
        for rawLine in contents.split(separator: "\n") {
            let line = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !line.isEmpty, !line.hasPrefix("#") else { continue }
            let parts = line.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
            guard parts.count == 2 else { continue }
            values[String(parts[0])] = String(parts[1])
        }
        return values
    }
}

private enum WatchLiveTOTP {
    static func generate(secret: String, date: Date = Date()) -> String {
        let secondsIntoWindow = Int(date.timeIntervalSince1970) % 30
        if secondsIntoWindow >= 25 {
            Thread.sleep(forTimeInterval: TimeInterval(30 - secondsIntoWindow + 2))
        }
        let key = SymmetricKey(data: base32Decode(secret))
        let counter = UInt64(floor(Date().timeIntervalSince1970 / 30.0))
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

@MainActor
private final class FakeWatchChatSyncSocket: WatchChatSyncSocket {
    private(set) var connectedSession: WatchSyncSession?
    private(set) var connectedSyncState: WatchSyncClientState?
    private(set) var didDisconnect = false

    func connect(session: WatchSyncSession, syncState: WatchSyncClientState) {
        connectedSession = session
        connectedSyncState = syncState
    }

    func disconnect() {
        didDisconnect = true
    }
}

@MainActor
private final class FakeWatchChatCrypto: WatchChatCrypto {
    private let decryptedValues: [String: String]
    private let omittedChatIds: Set<String>

    init(decryptedValues: [String: String] = [:], omittedChatIds: Set<String> = []) {
        self.decryptedValues = decryptedValues
        self.omittedChatIds = omittedChatIds
    }

    func decryptChat(_ chat: WatchRemoteChat) async -> WatchChatSummary? {
        guard !omittedChatIds.contains(chat.id) else { return nil }
        return WatchChatSummary(
            id: chat.id,
            title: chat.encryptedTitle.flatMap { decryptedValues[$0] } ?? chat.title,
            lastMessageAt: chat.lastMessageAt ?? chat.updatedAt,
            preview: chat.encryptedChatSummary.flatMap { decryptedValues[$0] } ?? chat.chatSummary,
            isPinned: chat.isPinned,
            encryptedTitle: chat.encryptedTitle,
            encryptedPreview: chat.encryptedChatSummary,
            encryptedChatKey: chat.encryptedChatKey
        )
    }

    func decryptMessage(_ message: WatchRemoteMessage) async -> WatchChatMessage {
        WatchChatMessage(
            id: message.id,
            chatId: message.chatId,
            role: message.role,
            content: message.encryptedContent.flatMap { decryptedValues[$0] } ?? message.content,
            encryptedContent: message.encryptedContent,
            createdAt: message.createdAt,
            isPending: false
        )
    }

    func encryptText(_ text: String, for chat: WatchChatSummary) async throws -> String {
        "encrypted:\(text)"
    }
}
