// Client-to-client PAKE pair login. The API relays opaque messages and grants;
// the approving Apple device alone holds OPAQUE server setup and registration.
// Specification: specifications/features/auth/specification.yml
// Assertions: auth.pair-login.single-use-zk, auth.pair-login.approval-assurance

import CryptoKit
import Foundation

// In-memory ownership for the existing authorizer relay; no PIN persistence.
struct PairV2Authorization: Sendable {
    let pin: String
    let expiresAt: Int
    let relayTask: Task<Void, Never>
}

enum PairSessionDeadlineStore {
    private static let userKey = "openmates.apple.pair_deadline_user"
    private static let deadlineKey = "openmates.apple.pair_deadline_seconds"

    static func save(userID: String, deadline: Int?) {
        clear()
        guard let deadline else { return }
        UserDefaults.standard.set(userID, forKey: userKey)
        UserDefaults.standard.set(deadline, forKey: deadlineKey)
    }

    static func isExpired(userID: String, now: Int = Int(Date().timeIntervalSince1970)) -> Bool {
        UserDefaults.standard.string(forKey: userKey) == userID
            && UserDefaults.standard.integer(forKey: deadlineKey) > 0
            && UserDefaults.standard.integer(forKey: deadlineKey) <= now
    }

    static func deadline(userID: String) -> Int? {
        guard UserDefaults.standard.string(forKey: userKey) == userID else { return nil }
        let deadline = UserDefaults.standard.integer(forKey: deadlineKey)
        return deadline > 0 ? deadline : nil
    }

    static func clear() {
        UserDefaults.standard.removeObject(forKey: userKey)
        UserDefaults.standard.removeObject(forKey: deadlineKey)
    }
}

enum PairPendingAckStore {
    private static let key = "openmates.apple.pair_pending_ack_user"

    static func mark(userID: String, defaults: UserDefaults = .standard) { defaults.set(userID, forKey: key) }
    static func userID(defaults: UserDefaults = .standard) -> String? { defaults.string(forKey: key) }
    static func flushLocalPairState(standard: UserDefaults = .standard,
                                    shared: UserDefaults = OpenMatesSharedEnvironment.defaults) throws {
        guard standard.synchronize() else {
            NativeDiagnostics.error("phase=persistence.flush.failed store=standard", category: "pair_login")
            throw PairOpaqueError.invalidExchange
        }
        guard shared === standard || shared.synchronize() else {
            NativeDiagnostics.error("phase=persistence.flush.failed store=app_group", category: "pair_login")
            throw PairOpaqueError.invalidExchange
        }
    }
    static func clear(defaults: UserDefaults = .standard) {
        defaults.removeObject(forKey: key)
        _ = defaults.synchronize()
    }
}

enum PairVerifiedAccountStore {
    private static let key = "openmates.apple.pair_verified_account"

    private struct Record: Codable {
        let userID: String
        let hashedEmail: String
        let emailSalt: String
        let encryptedEmail: String
    }

    static func save(userID: String, hashedEmail: String, emailSalt: String, encryptedEmail: String) throws {
        let data = try JSONEncoder().encode(Record(userID: userID, hashedEmail: hashedEmail,
            emailSalt: emailSalt, encryptedEmail: encryptedEmail))
        UserDefaults.standard.set(data, forKey: key)
    }

    static func clear() { UserDefaults.standard.removeObject(forKey: key) }
}

private struct PairV2Attempt: Sendable {
    let capability: String
    let hash: String
    let sessionID: String
    let expiresAt: Int
}

// Older password accounts predate the server-stored master-key email envelope.
// The server still binds the account's hash and salt to the authenticated user.
private struct PairV2BoundAccountCheck: Decodable {
    let userId: String
    let hashedEmail: String
    let encryptedEmailWithMasterKey: String?
    let userEmailSalt: String
}

private actor PairV2AttemptStore {
    static let shared = PairV2AttemptStore()
    private var attempts: [String: PairV2Attempt] = [:]

    func put(_ attempt: PairV2Attempt, token: String) {
        attempts[token] = attempt
    }

    func get(token: String) throws -> PairV2Attempt {
        guard let attempt = attempts[token], attempt.expiresAt > Int(Date().timeIntervalSince1970) else {
            attempts[token] = nil
            throw PairOpaqueError.invalidExchange
        }
        return attempt
    }

    func remove(token: String) { attempts[token] = nil }
}

struct PairV2EmailChallenge: Sendable {
    let challengeID: String
    let hashedEmail: String
    let sessionID: String
    let lookupHash: String?
    let passwordChallengeID: String?
    let passwordProof: String?
}

private struct PairV2EmailCodeRequest: Encodable {
    let purpose = "pair_approval"
    let email: String
    let sessionId: String
}

private struct PairV2EmailCodeVerify: Encodable {
    let purpose = "pair_approval"
    let challengeId: String
    let code: String
    let hashedEmail: String
    let sessionId: String
    let lookupHash: String?
    let passwordChallengeId: String?
    let passwordProof: String?
}

private struct PairV2EmailCodeRequestResponse: Decodable {
    let success: Bool
    let challengeId: String
    let expiresIn: Int
    let passwordChallengeId: String?
    let passwordNonce: String?
}

enum PairV2Runtime {
    private static let prefix = "/v1/auth/pair/v2"

    static func stepUpMethods(serverProfile: ServerProfile) async throws -> PairV2StepUpMethods {
        try await APIClient.shared.request(
            .get, path: "/v1/auth/methods", serverProfile: serverProfile
        )
    }

    static func stepUp(code: String, serverProfile: ServerProfile) async throws {
        guard code.range(of: "^[0-9]{6}$", options: .regularExpression) != nil else {
            throw PairOpaqueError.invalidExchange
        }
        let request = PairV2StepUpRequest(
            authMethod: "2fa_otp", hashedEmail: nil,
            lookupHash: nil, authCode: code
        )
        let response: PairV2StepUpResponse = try await APIClient.shared.request(
            .post, path: "\(prefix)/step-up", serverProfile: serverProfile, body: request
        )
        guard response.success, response.expiresIn > 0 else { throw PairOpaqueError.invalidExchange }
    }

    static func requestEmailStepUp(user: UserProfile, password: String,
                                   serverProfile: ServerProfile) async throws -> PairV2EmailChallenge {
        guard !password.isEmpty, let email = user.email, !email.isEmpty,
              let saltText = user.userEmailSalt,
              let salt = Data(base64Encoded: saltText) else {
            throw AuthError.missingAuthData
        }
        let hashedEmail = await CryptoManager.shared.hashEmail(email)
        let sessionID = WatchCompatibleSession.nativeSessionId
        let response: PairV2EmailCodeRequestResponse = try await APIClient.shared.request(
            .post, path: "/v1/auth/sensitive/email/request", serverProfile: serverProfile,
            body: PairV2EmailCodeRequest(email: email, sessionId: sessionID)
        )
        guard response.success, response.expiresIn > 0,
              !response.challengeId.isEmpty else { throw PairOpaqueError.invalidExchange }
        let lookupHash: String?
        let passwordProof: String?
        if user.credentialVersion == 2 {
            guard let nonceText = response.passwordNonce,
                  let nonce = Data(base64URLEncoded: nonceText),
                  response.passwordChallengeId != nil else { throw PairOpaqueError.invalidExchange }
            lookupHash = nil
            passwordProof = try PasswordV2Keys(password: password, emailSalt: salt)
                .proof(purpose: "sensitive:pair_approval", nonce: nonce)
        } else {
            lookupHash = await CryptoManager.shared.hashKey(password, salt: salt)
            passwordProof = nil
        }
        return PairV2EmailChallenge(
            challengeID: response.challengeId, hashedEmail: hashedEmail, sessionID: sessionID,
            lookupHash: lookupHash,
            passwordChallengeID: user.credentialVersion == 2 ? response.passwordChallengeId : nil,
            passwordProof: passwordProof
        )
    }

    static func verifyEmailStepUp(_ challenge: PairV2EmailChallenge, code: String,
                                  serverProfile: ServerProfile) async throws {
        guard code.range(of: "^[0-9]{6}$", options: .regularExpression) != nil else {
            throw PairOpaqueError.invalidExchange
        }
        let response: PairV2StepUpResponse = try await APIClient.shared.request(
            .post, path: "/v1/auth/sensitive/email/verify", serverProfile: serverProfile,
            body: PairV2EmailCodeVerify(
                challengeId: challenge.challengeID, code: code,
                hashedEmail: challenge.hashedEmail, sessionId: challenge.sessionID,
                lookupHash: challenge.lookupHash,
                passwordChallengeId: challenge.passwordChallengeID,
                passwordProof: challenge.passwordProof
            )
        )
        guard response.success, response.expiresIn > 0 else { throw PairOpaqueError.invalidExchange }
    }

    private static func headers(_ attempt: PairV2Attempt) -> [String: String] {
        ["X-OpenMates-Pair-Receiver": attempt.capability]
    }

    private static func opaqueMessage(_ value: String) throws -> String {
        guard value.utf8.count <= 10_926, try PairV2Crypto.decode(value).count <= 8_192 else {
            throw PairOpaqueError.invalidExchange
        }
        return value
    }

    static func initiate(deviceHint: String, serverProfile: ServerProfile) async throws -> PairLoginInitiation {
        let secret = try SecureRandom.data(count: 32)
        let attempt = PairV2Attempt(
            capability: PairV2Crypto.encode(secret),
            hash: PairV2Crypto.hash(secret),
            sessionID: WatchCompatibleSession.nativeSessionId,
            expiresAt: 0
        )
        let response: PairV2InitiateResponse = try await APIClient.shared.request(
            .post, path: "\(prefix)/initiate", serverProfile: serverProfile,
            body: PairV2InitiateRequest(
                receiverTokenHash: attempt.hash,
                sessionId: attempt.sessionID,
                deviceHint: deviceHint
            )
        )
        guard response.protocolVersion == 2,
              response.token.range(of: "^[A-Z0-9]{6}$", options: .regularExpression) != nil,
              response.expiresAt > Int(Date().timeIntervalSince1970) else {
            throw PairOpaqueError.invalidExchange
        }
        await PairV2AttemptStore.shared.put(
            PairV2Attempt(capability: attempt.capability, hash: attempt.hash,
                          sessionID: attempt.sessionID, expiresAt: response.expiresAt),
            token: response.token
        )
        if Task.isCancelled {
            await cancel(token: response.token, serverProfile: serverProfile)
            throw CancellationError()
        }
        return PairLoginInitiation(
            token: response.token,
            pairURLString: PairLoginRuntime.buildPairURL(webAppURL: serverProfile.webBaseURL, token: response.token)
        )
    }

    static func poll(token: String, serverProfile: ServerProfile) async throws -> PairV2ReceiverPoll {
        let attempt = try await PairV2AttemptStore.shared.get(token: token)
        let value: PairV2ReceiverPoll = try await APIClient.shared.request(
            .get, path: "\(prefix)/receiver/\(token)", serverProfile: serverProfile,
            headers: headers(attempt)
        )
        guard value.expiresAt == attempt.expiresAt else { throw PairOpaqueError.invalidExchange }
        return value
    }

    static func complete(token: String, pin: String, serverProfile: ServerProfile) async throws -> PairLoginResult {
        var stage = "receiver_attempt"
        do {
            let attempt = try await PairV2AttemptStore.shared.get(token: token)
            stage = "approval_context"
            let approved = try await poll(token: token, serverProfile: serverProfile)
            guard approved.status == "approved",
                  approved.sessionId == attempt.sessionID,
                  approved.receiverTokenHash == attempt.hash,
                  let authorizerUserID = approved.authorizerUserId,
                  PairLoginRuntime.isValidPIN(pin) else {
                throw PairOpaqueError.invalidExchange
            }
            let context = try PairV2Context(
                token: token,
                sessionID: attempt.sessionID,
                receiverTokenHash: attempt.hash,
                authorizerUserID: authorizerUserID,
                autoLogoutMinutes: approved.autoLogoutMinutes
            )
            stage = "opaque_start"
            let start = try PairOpaque.call("startClientLogin", ["password": pin])
            try Task.checkCancellation()
            stage = "receiver_request"
            let _: Data = try await APIClient.shared.request(
                .post, path: "\(prefix)/receiver/\(token)/message", serverProfile: serverProfile,
                body: PairV2MessageRequest(stage: "request", message: try PairOpaque.field(start, "startLoginRequest")),
                headers: headers(attempt)
            )
            stage = "authorizer_response"
            let response = try await waitForReceiver(token: token, status: "response", serverProfile: serverProfile)
            try Task.checkCancellation()
            guard let rawMessage = response.message else { throw PairOpaqueError.invalidExchange }
            let message = try opaqueMessage(rawMessage)
            stage = "opaque_finish"
            let finish = try PairOpaque.call("finishClientLogin", [
                "clientLoginState": try PairOpaque.field(start, "clientLoginState"),
                "loginResponse": message,
                "password": pin,
                "identifiers": context.identifiers
            ])
            try Task.checkCancellation()
            stage = "receiver_finish"
            let _: Data = try await APIClient.shared.request(
                .post, path: "\(prefix)/receiver/\(token)/message", serverProfile: serverProfile,
                body: PairV2MessageRequest(stage: "finish", message: try PairOpaque.field(finish, "finishLoginRequest")),
                headers: headers(attempt)
            )
            stage = "authorizer_bundle"
            let ready = try await waitForReceiver(token: token, status: "ready", serverProfile: serverProfile)
            try Task.checkCancellation()
            guard let encrypted = ready.encryptedBundle, let iv = ready.iv else { throw PairOpaqueError.invalidExchange }
            stage = "bundle_decrypt"
            let plaintext = try PairV2Crypto.open(
                ciphertext: encrypted, iv: iv,
                sessionKey: try PairOpaque.field(finish, "sessionKey"), context: context
            )
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            stage = "bundle_binding"
            let bundle = try decoder.decode(PairV2Bundle.self, from: plaintext)
            guard bundle.protocolVersion == 2,
                  bundle.userId == context.authorizerUserID,
                  try PairV2Crypto.decode(bundle.grantSecret).count == 32,
                  let masterKeyData = Data(base64Encoded: bundle.masterKeyExported), masterKeyData.count == 32 else {
                throw PairOpaqueError.invalidExchange
            }
            let masterKey = SymmetricKey(data: masterKeyData)
            stage = "account_binding"
            let decryptedEmail = try await CryptoManager.shared.decryptContent(
                base64String: bundle.accountContext.encryptedEmailWithMasterKey, key: masterKey
            )
            guard !decryptedEmail.isEmpty,
                  await CryptoManager.shared.hashEmail(decryptedEmail) == bundle.hashedEmail else {
                throw PairOpaqueError.invalidExchange
            }
            try Task.checkCancellation()
            stage = "session_complete"
            let login: LoginResponse = try await APIClient.shared.request(
                .post, path: "\(prefix)/complete/\(token)", serverProfile: serverProfile,
                body: PairV2CompleteRequest(grantSecret: bundle.grantSecret), headers: headers(attempt)
            )
            stage = "session_identity"
            guard login.success, login.user?.id == context.authorizerUserID,
                  context.autoLogoutMinutes == nil || (login.pairExpiresAt ?? 0) > Int(Date().timeIntervalSince1970) else {
                throw PairOpaqueError.invalidExchange
            }
            stage = "session_account_binding"
            guard login.user?.userEmailSalt == bundle.userEmailSalt,
                  login.user?.email == nil || login.user?.email == decryptedEmail else {
                throw PairOpaqueError.invalidExchange
            }
            try Task.checkCancellation()
            stage = "account_persist"
            try PairVerifiedAccountStore.save(userID: bundle.userId, hashedEmail: bundle.hashedEmail,
                emailSalt: bundle.userEmailSalt, encryptedEmail: bundle.accountContext.encryptedEmailWithMasterKey)
            return PairLoginResult(loginResponse: login, masterKey: masterKey, serverProfile: serverProfile)
        } catch {
            NativeDiagnostics.error("phase=receiver.complete.failed stage=\(stage) errorType=\(type(of: error))", category: "pair_login")
            throw error
        }
    }

    static func acknowledge(token: String, serverProfile: ServerProfile) async throws {
        let attempt = try await PairV2AttemptStore.shared.get(token: token)
        var lastError: Error = PairOpaqueError.invalidExchange
        for retry in 0..<3 {
            do {
                let _: Data = try await APIClient.shared.request(
                    .post, path: "\(prefix)/acknowledge/\(token)", serverProfile: serverProfile,
                    headers: headers(attempt)
                )
                await PairV2AttemptStore.shared.remove(token: token)
                return
            } catch {
                lastError = error
                if retry < 2 { try await Task.sleep(for: .milliseconds(Int64(250 * (retry + 1)))) }
            }
        }
        throw lastError
    }

    static func cancel(token: String, serverProfile: ServerProfile) async {
        guard let attempt = try? await PairV2AttemptStore.shared.get(token: token) else { return }
        let _: Data? = try? await APIClient.shared.request(
            .delete, path: "\(prefix)/\(token)", serverProfile: serverProfile,
            headers: headers(attempt)
        )
        await PairV2AttemptStore.shared.remove(token: token)
    }

    private static func waitForReceiver(token: String, status: String, serverProfile: ServerProfile) async throws -> PairV2ReceiverPoll {
        for _ in 0..<180 {
            try Task.checkCancellation()
            let value = try await poll(token: token, serverProfile: serverProfile)
            if value.status == status { return value }
            if ["failed", "cancelled", "acknowledged"].contains(value.status) { throw PairOpaqueError.invalidExchange }
            try await Task.sleep(for: .seconds(1))
        }
        throw PairOpaqueError.invalidExchange
    }

    static func authorize(
        token: String, currentUser: UserProfile, authorizerDeviceName: String,
        autoLogoutMinutes: Int?, serverProfile: ServerProfile
    ) async throws -> String {
        try await startAuthorization(token: token, currentUser: currentUser,
            authorizerDeviceName: authorizerDeviceName, autoLogoutMinutes: autoLogoutMinutes,
            serverProfile: serverProfile).pin
    }

    static func startAuthorization(
        token: String, currentUser: UserProfile, authorizerDeviceName: String,
        autoLogoutMinutes: Int?, serverProfile: ServerProfile
    ) async throws -> PairV2Authorization {
        let info: PairV2InfoResponse = try await APIClient.shared.request(
            .get, path: "\(prefix)/info/\(token)", serverProfile: serverProfile
        )
        guard info.protocolVersion == 2, info.expiresAt > Int(Date().timeIntervalSince1970) else {
            throw PairOpaqueError.invalidExchange
        }
        let approved: PairV2ApproveResponse = try await APIClient.shared.request(
            .post, path: "\(prefix)/approve/\(token)", serverProfile: serverProfile,
            body: PairV2ApproveRequest(authorizerDeviceName: authorizerDeviceName, autoLogoutMinutes: autoLogoutMinutes)
        )
        guard approved.success, approved.protocolVersion == 2, approved.token == token,
              approved.sessionId == info.sessionId,
              approved.receiverTokenHash == info.receiverTokenHash,
              approved.authorizerUserId == currentUser.id,
              approved.autoLogoutMinutes == autoLogoutMinutes,
              approved.expiresAt == info.expiresAt else {
            throw PairOpaqueError.invalidExchange
        }
        let context = try PairV2Context(
            token: token, sessionID: info.sessionId,
            receiverTokenHash: info.receiverTokenHash,
            authorizerUserID: currentUser.id,
            autoLogoutMinutes: autoLogoutMinutes
        )
        let pin = try PairLoginRuntime.generatePairPIN()
        let setup = try PairOpaque.call("createServerSetup")
        let registration = try PairOpaque.call("startClientRegistration", ["password": pin])
        let registrationResponse = try PairOpaque.call("createServerRegistrationResponse", [
            "serverSetup": try PairOpaque.field(setup, "serverSetup"),
            "userIdentifier": context.userIdentifier,
            "registrationRequest": try PairOpaque.field(registration, "registrationRequest")
        ])
        let record = try PairOpaque.call("finishClientRegistration", [
            "password": pin,
            "clientRegistrationState": try PairOpaque.field(registration, "clientRegistrationState"),
            "registrationResponse": try PairOpaque.field(registrationResponse, "registrationResponse"),
            "identifiers": context.identifiers
        ])
        try Task.checkCancellation()
        let relayTask = Task {
            do {
                try await serveAuthorizer(
                    token: token, context: context,
                    setup: try PairOpaque.field(setup, "serverSetup"),
                    record: try PairOpaque.field(record, "registrationRecord"),
                    user: currentUser, serverProfile: serverProfile
                )
            } catch {
                NativeDiagnostics.error("phase=authorizer.failed errorType=\(type(of: error))", category: "pair_login")
                let _: Data? = try? await APIClient.shared.request(
                    .delete, path: "\(prefix)/\(token)", serverProfile: serverProfile
                )
            }
        }
        return PairV2Authorization(pin: pin, expiresAt: approved.expiresAt, relayTask: relayTask)
    }

    private static func serveAuthorizer(
        token: String, context: PairV2Context, setup: String, record: String,
        user: UserProfile, serverProfile: ServerProfile
    ) async throws {
        let request = try await waitForAuthorizer(token: token, status: "request", serverProfile: serverProfile)
        guard let rawClientMessage = request.receiverRequest else { throw PairOpaqueError.invalidExchange }
        let clientMessage = try opaqueMessage(rawClientMessage)
        let start = try PairOpaque.call("startServerLogin", [
            "serverSetup": setup, "registrationRecord": record,
            "startLoginRequest": clientMessage,
            "userIdentifier": context.userIdentifier,
            "identifiers": context.identifiers
        ])
        try Task.checkCancellation()
        let _: Data = try await APIClient.shared.request(
            .post, path: "\(prefix)/authorizer/\(token)/message", serverProfile: serverProfile,
            body: PairV2MessageRequest(stage: "response", message: try PairOpaque.field(start, "loginResponse"))
        )
        let finish = try await waitForAuthorizer(token: token, status: "finish", serverProfile: serverProfile)
        guard let rawFinalMessage = finish.receiverFinish else { throw PairOpaqueError.invalidExchange }
        let finalMessage = try opaqueMessage(rawFinalMessage)
        let result = try PairOpaque.call("finishServerLogin", [
            "serverLoginState": try PairOpaque.field(start, "serverLoginState"),
            "finishLoginRequest": finalMessage,
            "identifiers": context.identifiers
        ])
        try Task.checkCancellation()
        guard let masterKey = try await CryptoManager.shared.loadMasterKey(for: user.id) else {
            throw AuthError.missingAuthData
        }
        let account: PairV2BoundAccountCheck = try await APIClient.shared.request(
            .get, path: "\(prefix)/account-check", serverProfile: serverProfile
        )
        guard account.userId == user.id,
              account.userEmailSalt == user.userEmailSalt else {
            throw PairOpaqueError.invalidExchange
        }
        let decryptedEmail: String
        let encryptedEmail: String
        if let serverEnvelope = account.encryptedEmailWithMasterKey {
            // A present envelope must decrypt and match; do not fall back to a
            // local value if the server-bound metadata is corrupt or mismatched.
            decryptedEmail = try await CryptoManager.shared.decryptContent(
                base64String: serverEnvelope, key: masterKey
            )
            encryptedEmail = serverEnvelope
        } else {
            guard let localEmail = user.email, !localEmail.isEmpty else {
                throw PairOpaqueError.invalidExchange
            }
            decryptedEmail = localEmail
            encryptedEmail = try await CryptoManager.shared.encryptWithMasterKey(
                localEmail, masterKey: masterKey
            )
        }
        let hashedEmail = await CryptoManager.shared.hashEmail(decryptedEmail)
        guard !decryptedEmail.isEmpty, hashedEmail == account.hashedEmail,
              user.email == nil || user.email == decryptedEmail else {
            throw PairOpaqueError.invalidExchange
        }
        let grantData = try SecureRandom.data(count: 32)
        let grantSecret = PairV2Crypto.encode(grantData)
        let grantHash = PairV2Crypto.hash(grantData)
        let masterKeyExported = masterKey.withUnsafeBytes { Data($0).base64EncodedString() }
        let bundle = try JSONSerialization.data(withJSONObject: [
            "protocol_version": 2,
            "master_key_exported": masterKeyExported,
            "grant_secret": grantSecret,
            "user_email_salt": account.userEmailSalt,
            "hashed_email": account.hashedEmail,
            "user_id": user.id,
            "account_context": ["encrypted_email_with_master_key": encryptedEmail]
        ])
        let encrypted = try PairV2Crypto.seal(
            bundle, sessionKey: try PairOpaque.field(result, "sessionKey"), context: context
        )
        try Task.checkCancellation()
        let _: Data = try await APIClient.shared.request(
            .post, path: "\(prefix)/authorize/\(token)", serverProfile: serverProfile,
            body: PairV2BundleRequest(
                encryptedBundle: encrypted.ciphertext, iv: encrypted.iv, grantHash: grantHash
            )
        )
    }

    static func authorizerPoll(token: String, serverProfile: ServerProfile) async throws -> PairV2AuthorizerPoll {
        try await APIClient.shared.request(.get, path: "\(prefix)/authorizer/\(token)", serverProfile: serverProfile)
    }

    private static func waitForAuthorizer(token: String, status: String, serverProfile: ServerProfile) async throws -> PairV2AuthorizerPoll {
        for _ in 0..<180 {
            try Task.checkCancellation()
            let value = try await authorizerPoll(token: token, serverProfile: serverProfile)
            if value.status == status { return value }
            if ["failed", "cancelled", "acknowledged"].contains(value.status) { throw PairOpaqueError.invalidExchange }
            try await Task.sleep(for: .seconds(1))
        }
        throw PairOpaqueError.invalidExchange
    }
}
