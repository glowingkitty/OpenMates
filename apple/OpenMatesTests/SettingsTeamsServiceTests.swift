import CryptoKit
import ImageIO
import UniformTypeIdentifiers
import XCTest
@testable import OpenMates

@MainActor
final class SettingsTeamsServiceTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=teams.lifecycle.encrypted-profiled,teams.membership.role-gated,apple-workspaces.maintenance,apple-workspaces.isolation
    func testMemberPortraitSurvivesActualRosterMaintenanceAndOfflineReloadThenTeamPurge() async throws {
        for uploaded in [false, true] {
            let scope = SettingsTeamsTestScope(), reader = SettingsTeamsTestReader()
            let base = makeSettingsTestTeam("portrait-maintenance-team", role: .viewer)
            let team = TeamWorkspaceTeam(id: base.id, name: base.name, description: base.description, role: base.role, status: base.status,
                profileImageMetadata: uploaded ? .init(version: 1, mode: "uploaded", iconName: "team", iconColor: "#ffffff", backgroundColor: "#4d73ff", imageURL: "/v1/teams/portrait-maintenance-team/profile-image") : .generated,
                zeroBalance: 0, createdAt: 1, updatedAt: 1, key: base.key)
            reader.team = team
            let key = SymmetricKey(size: .bits256), pixels = try testMemberAvatarJPEG()
            let directory = FileManager.default.temporaryDirectory.appendingPathComponent("member-maintenance-" + UUID().uuidString)
            defer { try? FileManager.default.removeItem(at: directory) }
            let member = SettingsTeamMember(id: "portrait-user", userID: "portrait-user", name: "Member", role: .member, status: "active",
                profileImageURL: "/v1/teams/portrait-maintenance-team/members/portrait-user/profile-image")
            let online = SettingsTeamsService(reader: reader, transport: { _, _, _, _ in pixels }, masterKey: { _ in key },
                responseCache: NativeWorkspaceOfflineCache(directory: directory))
            let retained = try await online.memberAvatar(team: team, member: member, fence: scope.fence)
            XCTAssertEqual(retained, pixels)
            let maintenance = NativeWorkspaceOfflineCache(directory: directory)
            var requestedTeamAvatar = false
            let refresh: TeamWorkspaceOfflineRetention.Transport = { path, _ in
                let route = try XCTUnwrap(URLComponents(string: "https://fixture.invalid" + path)?.path)
                let body: [String: Any]
                switch route {
                case "/v1/chats": body = ["chats": []]
                case "/v1/workflows": body = ["workflows": []]
                case "/v1/user-tasks": body = ["tasks": [], "complete": true]
                case "/v1/user-plans": body = ["plans": [], "complete": true]
                case "/v1/projects": body = ["projects": []]
                case "/v1/teams/portrait-maintenance-team/members": body = ["members": [["user_id": "portrait-user", "role": "member", "status": "active", "profile_image_url": member.profileImageURL!]]]
                case "/v1/teams/portrait-maintenance-team/memories": body = ["memories": []]
                case "/v1/teams/portrait-maintenance-team/profile-image": requestedTeamAvatar = true; return pixels
                default: throw TeamWorkspaceError.invalidResponse
                }
                return try JSONSerialization.data(withJSONObject: body)
            }
            try await TeamWorkspaceOfflineRetention.retain(fence: scope.fence, teams: [team], removedIDs: [], masterKey: key,
                cache: maintenance, transport: refresh, membership: { id, _ in XCTAssertEqual(id, team.id); return team })
            let captured = NativeWorkspaceOfflineScope(accountID: scope.accountID, server: scope.server.apiBaseURL.absoluteString,
                teamID: team.id, accountGeneration: scope.scope, teamEpoch: TeamWorkspaceContext.shared.contextEpoch)
            await maintenance.configure(scope: captured, masterKey: key)
            let completed = try await maintenance.hasCompleteSnapshot(namespace: "team-images", scope: captured)
            let currentTeamPixels = try await maintenance.read(namespace: "team-images", path: "/v1/teams/portrait-maintenance-team/profile-image", scope: captured)
            XCTAssertTrue(completed, "Assert the real maintenance replacement occurred before offline retrieval")
            XCTAssertEqual(requestedTeamAvatar, uploaded); XCTAssertEqual(currentTeamPixels, uploaded ? pixels : nil)
            reader.offlineDetails = true
            let offline = SettingsTeamsService(reader: reader, transport: { _, _, _, _ in throw URLError(.notConnectedToInternet) },
                masterKey: { _ in key }, responseCache: NativeWorkspaceOfflineCache(directory: directory))
            let restored = try await offline.memberAvatar(team: team, member: member, fence: scope.fence)
            XCTAssertEqual(restored, pixels, "Generated empty and uploaded single-image maintenance snapshots must both preserve member portraits")
            try await TeamWorkspaceOfflineRetention.retain(fence: scope.fence, teams: [], removedIDs: [team.id], masterKey: key,
                cache: maintenance, transport: refresh, membership: { _, _ in throw TeamWorkspaceError.unavailableTeam })
            let purgedStore = NativeWorkspaceOfflineCache(directory: directory)
            await purgedStore.configure(scope: captured, masterKey: key)
            let afterRemoval = try await purgedStore.read(namespace: "team-member-images", path: member.profileImageURL!, scope: captured)
            XCTAssertNil(afterRemoval, "Whole-Team revocation purge must include the separate member namespace")
            XCTAssertFalse(FileManager.default.fileExists(atPath: directory.appendingPathComponent(captured.directoryID).path))
        }
    }

    // contract-test: supporting surface=gui.apple assertions=teams.lifecycle.encrypted-profiled,teams.context.full-switch-local
    func testAcceptedUploadThenReadFailureCanRecoverGeneratedWithoutCreatingAnotherTeam() async throws {
        let scope = SettingsTeamsTestScope(), reader = SettingsTeamsTestReader(), master = SymmetricKey(size: .bits256)
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("accepted-image-recovery-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let context = TeamWorkspaceSnapshot(accountID: scope.accountID, server: scope.server, scope: scope.scope, teamID: nil, epoch: 1)
        var creates = 0, uploads = 0, generatedSaves = 0, serverMode = "generated"
        let service = SettingsTeamsService(reader: reader, transport: { method, path, bytes, _ in
            if path == "/v1/teams/name-approval" { return Data(#"{"approval_token":"approved"}"#.utf8) }
            if method == .get { throw URLError(.notConnectedToInternet) }
            let payload = try XCTUnwrap(JSONSerialization.jsonObject(with: XCTUnwrap(bytes)) as? [String: Any])
            if method == .post, path == "/v1/teams" {
                creates += 1
                let id = try XCTUnwrap(payload["team_id"] as? String)
                let key = try await CryptoManager.shared.unwrapChatKey(encryptedChatKeyBase64: XCTUnwrap(payload["encrypted_team_key"] as? String), masterKey: master)
                reader.team = TeamWorkspaceTeam(id: id, name: "Recoverable team", description: "", role: .owner, status: "active",
                    profileImageMetadata: .generated, zeroBalance: 0, createdAt: 1, updatedAt: 1, key: key)
                return try JSONSerialization.data(withJSONObject: ["team": ["team_id": id]])
            }
            XCTAssertEqual(method, .patch); XCTAssertEqual(path, "/v1/teams/" + (reader.team?.id ?? ""))
            let text = try await CryptoManager.shared.decryptContent(base64String: XCTUnwrap(payload["encrypted_profile_image_metadata"] as? String), key: XCTUnwrap(reader.team).key)
            let metadata = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any])
            XCTAssertEqual(metadata["mode"] as? String, "generated"); XCTAssertEqual(metadata["icon_name"] as? String, "team")
            XCTAssertEqual(metadata["background_color"] as? String, "#4d73ff")
            XCTAssertNil(payload["mode"]); generatedSaves += 1; serverMode = "generated"
            return Data(#"{}"#.utf8)
        }, masterKey: { _ in master }, avatarUpload: { _, _, _, _, _ in
            uploads += 1; serverMode = "uploaded"
            reader.nextDetailError = URLError(.networkConnectionLost)
            return Data(#"{"status":"ok"}"#.utf8)
        }, contextSnapshot: { context }, contextIsCurrent: { $0.scope == scope.scope }, responseCache: NativeWorkspaceOfflineCache(directory: directory))
        let controller = SettingsTeamsController(service: service, environment: scope.environment)
        await controller.load(accountID: scope.accountID)
        let approved = await controller.continueCreation(name: "Recoverable team"); XCTAssertTrue(approved)
        let uncertain = await controller.create(name: "Recoverable team", description: "", jpeg: Data([1]))
        XCTAssertFalse(uncertain); XCTAssertNotNil(controller.createdForDraft); XCTAssertEqual(serverMode, "uploaded")
        let recovered = await controller.create(name: "Recoverable team", description: "", icon: "team", color: "#4d73ff")
        XCTAssertTrue(recovered); XCTAssertEqual(creates, 1); XCTAssertEqual(uploads, 1)
        XCTAssertEqual(generatedSaves, 1, "Original generated values still require an encrypted PATCH after an uncertain accepted upload")
        XCTAssertEqual(serverMode, "generated"); XCTAssertNil(controller.createdForDraft)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.lifecycle.encrypted-profiled,teams.membership.role-gated
    func testCreationChecksNameBeforeMutationAndRetriesSameTeamAfterRejectedUpload() async {
        let scope = SettingsTeamsTestScope(), service = SettingsTeamsCreationTestService()
        let controller = SettingsTeamsController(service: service, environment: scope.environment)
        await controller.load(accountID: scope.accountID)
        let unchecked = await controller.create(name: "Chosen team", description: "")
        XCTAssertFalse(unchecked); XCTAssertEqual(service.createCalls, 0)
        let approved = await controller.continueCreation(name: "  Chosen team  ")
        XCTAssertTrue(approved); XCTAssertEqual(service.checkedNames, ["Chosen team"]); XCTAssertTrue(controller.teams.isEmpty)
        service.rejectUpload = true
        let failed = await controller.create(name: "Chosen team", description: "", icon: "heart", color: "#e35d6a", jpeg: Data([1]))
        XCTAssertFalse(failed); XCTAssertTrue(controller.creationFailed); XCTAssertTrue(controller.imageRejected)
        XCTAssertEqual(controller.createdForDraft?.id, "created-once"); XCTAssertNil(controller.selectedID)
        XCTAssertEqual(service.createCalls, 1); XCTAssertEqual(controller.teams.count, 1)
        service.rejectUpload = false
        let retried = await controller.create(name: "Chosen team", description: "", icon: "heart", color: "#e35d6a", jpeg: Data([1]))
        XCTAssertTrue(retried); XCTAssertEqual(service.createCalls, 1)
        XCTAssertEqual(service.uploadedIDs, ["created-once", "created-once"])
        XCTAssertEqual(controller.selectedID, "created-once"); XCTAssertNil(controller.createdForDraft)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.lifecycle.encrypted-profiled,teams.context.full-switch-local
    func testCanceledNameCheckCannotAdvanceOrApproveAnotherCreationDraft() async {
        let scope = SettingsTeamsTestScope(), service = SettingsTeamsCreationTestService()
        let controller = SettingsTeamsController(service: service, environment: scope.environment)
        await controller.load(accountID: scope.accountID)
        let gate = expectation(description: "name approval suspended")
        service.nameGate = gate
        let old = Task { await controller.continueCreation(name: "Old draft") }
        await fulfillment(of: [gate], timeout: 3)
        controller.cancelCreationCheck(); controller.beginCreation()
        service.nameContinuation?.resume(); service.nameContinuation = nil
        let advanced = await old.value
        XCTAssertFalse(advanced); XCTAssertFalse(controller.checkingName)
        let created = await controller.create(name: "Old draft", description: "")
        XCTAssertFalse(created); XCTAssertEqual(service.createCalls, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.lifecycle.encrypted-profiled,teams.context.full-switch-local
    func testAccountResetCannotPublishSuspendedNameApprovalOrCreatedTeam() async {
        let scope = SettingsTeamsTestScope(), service = SettingsTeamsCreationTestService()
        let controller = SettingsTeamsController(service: service, environment: scope.environment)
        await controller.load(accountID: scope.accountID)
        let gate = expectation(description: "old account approval suspended")
        service.nameGate = gate
        let old = Task { await controller.continueCreation(name: "Private old draft") }
        await fulfillment(of: [gate], timeout: 3)
        scope.accountID = "different-account"; scope.scope = UUID(); controller.reset()
        service.nameContinuation?.resume(); service.nameContinuation = nil
        let advanced = await old.value
        XCTAssertFalse(advanced); XCTAssertTrue(controller.teams.isEmpty); XCTAssertNil(controller.createdForDraft)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.lifecycle.encrypted-profiled
    func testCreateEncryptsChosenGeneratedAvatarInInitialPayloadAndReapprovesName() async throws {
        let scope = SettingsTeamsTestScope(), master = SymmetricKey(size: .bits256)
        var approvals = 0, creates = 0
        let service = SettingsTeamsService(transport: { _, path, bytes, _ in
            if path == "/v1/teams/name-approval" { approvals += 1; return Data(#"{"approval_token":"fresh-name-token"}"#.utf8) }
            XCTAssertEqual(path, "/v1/teams"); creates += 1
            let payload = try XCTUnwrap(JSONSerialization.jsonObject(with: XCTUnwrap(bytes)) as? [String: Any])
            let key = try await CryptoManager.shared.unwrapChatKey(encryptedChatKeyBase64: XCTUnwrap(payload["encrypted_team_key"] as? String), masterKey: master)
            let text = try await CryptoManager.shared.decryptContent(base64String: XCTUnwrap(payload["encrypted_profile_image_metadata"] as? String), key: key)
            let metadata = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any])
            XCTAssertEqual(metadata["icon_name"] as? String, "design"); XCTAssertEqual(metadata["background_color"] as? String, "#db8f36")
            XCTAssertNil(payload["icon_name"]); XCTAssertNil(payload["background_color"])
            XCTAssertEqual(payload["name_approval_token"] as? String, "fresh-name-token")
            return try JSONSerialization.data(withJSONObject: ["team": ["team_id": payload["team_id"]!]])
        }, masterKey: { _ in master })
        try await service.checkCreationName("Chosen team", fence: scope.fence)
        XCTAssertEqual(creates, 0)
        let team = try await service.createProfiledAvatar(name: "Chosen team", description: "", memberName: "Owner", icon: "design", color: "#db8f36", fence: scope.fence)
        XCTAssertEqual(approvals, 2); XCTAssertEqual(creates, 1)
        XCTAssertEqual(team.profileImageMetadata.iconName, "design"); XCTAssertEqual(team.name, "Chosen team")
    }

    // contract-test: supporting surface=gui.apple assertions=teams.membership.role-gated,teams.lifecycle.encrypted-profiled
    func testMemberProfileKeepsEncryptedGeneratedAvatarAndExactUploadedRoute() async throws {
        let scope = SettingsTeamsTestScope(), team = makeSettingsTestTeam("member-team", role: .viewer)
        let profile = try await CryptoManager.shared.encryptWithMasterKey(##"{"display_name":"Private teammate","avatar":{"mode":"generated","icon_name":"heart","background_color":"#e35d6a"}}"##, masterKey: team.key)
        let route = "/v1/teams/member-team/members/member-user/profile-image"
        let service = SettingsTeamsService(transport: { _, path, _, _ in
            XCTAssertEqual(path, "/v1/teams/member-team/members")
            return try JSONSerialization.data(withJSONObject: ["members": [["user_id":"member-user","role":"member","status":"active","encrypted_member_profile":profile,"profile_image_url":route]]])
        })
        let rows = try await service.management(team: team, fence: scope.fence).members
        let member = try XCTUnwrap(rows.first)
        XCTAssertEqual(member.name, "Private teammate"); XCTAssertEqual(member.avatarIcon, "heart")
        XCTAssertEqual(member.avatarColor, "#e35d6a"); XCTAssertEqual(member.profileImageURL, route)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.membership.role-gated,teams.context.full-switch-local
    func testMemberAvatarRejectsForeignRouteAndRevocationBeforeCachingPixels() async throws {
        let scope = SettingsTeamsTestScope(), reader = SettingsTeamsTestReader()
        let team = makeSettingsTestTeam("member-team", role: .viewer)
        reader.team = team
        let raw = try testMemberAvatarJPEG()
        var calls = 0
        let service = SettingsTeamsService(reader: reader, transport: { _, path, _, _ in
            calls += 1; XCTAssertEqual(path, "/v1/teams/member-team/members/member-user/profile-image")
            reader.team = TeamWorkspaceTeam(id: team.id, name: team.name, description: team.description, role: team.role, status: "removed",
                profileImageMetadata: team.profileImageMetadata, zeroBalance: 0, createdAt: 1, updatedAt: 2, key: team.key)
            return raw
        }, masterKey: { _ in SymmetricKey(size: .bits256) })
        var member = SettingsTeamMember(id: "member-user", userID: "member-user", name: "Member", role: .member, status: "active", profileImageURL: "https://foreign.invalid/private.jpg")
        let foreign = try await service.memberAvatar(team: team, member: member, fence: scope.fence)
        XCTAssertNil(foreign); XCTAssertEqual(calls, 0)
        member.profileImageURL = "/v1/teams/member-team/members/member-user/profile-image"
        do { _ = try await service.memberAvatar(team: team, member: member, fence: scope.fence); XCTFail("Revoked Team must not cache or return pixels") }
        catch SettingsTeamsError.permissionDenied { }
        XCTAssertEqual(calls, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.lifecycle.encrypted-profiled,teams.membership.role-gated,teams.context.full-switch-local
    func testMemberAvatarCiphertextSurvivesOfflineReloadButNeverMasksAuthorizationFailure() async throws {
        let scope = SettingsTeamsTestScope(), reader = SettingsTeamsTestReader()
        let team = makeSettingsTestTeam("member-cache-team", role: .viewer), key = SymmetricKey(size: .bits256)
        reader.team = team
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("teams-member-pixels-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let raw = try testMemberAvatarJPEG()
        let member = SettingsTeamMember(id: "member-user", userID: "member-user", name: "Member", role: .member, status: "active",
            profileImageURL: "/v1/teams/member-cache-team/members/member-user/profile-image")
        let online = SettingsTeamsService(reader: reader, transport: { _, _, _, _ in raw }, masterKey: { _ in key },
            responseCache: NativeWorkspaceOfflineCache(directory: directory))
        let first = try await online.memberAvatar(team: team, member: member, fence: scope.fence)
        XCTAssertEqual(first, raw)
        reader.offlineDetails = true
        var forbidden = false
        let offline = SettingsTeamsService(reader: reader, transport: { _, _, _, _ in
            if forbidden { throw APIError.httpError(status: 403, message: "Denied") }
            throw URLError(.notConnectedToInternet)
        }, masterKey: { _ in key }, responseCache: NativeWorkspaceOfflineCache(directory: directory))
        let restored = try await offline.memberAvatar(team: team, member: member, fence: scope.fence)
        XCTAssertEqual(restored, raw, "A new service can decrypt the authorized retained image offline")
        forbidden = true
        do { _ = try await offline.memberAvatar(team: team, member: member, fence: scope.fence); XCTFail("403 must not return cached pixels") }
        catch APIError.httpError(let status, _) { XCTAssertEqual(status, 403) }
    }

    // contract-test: supporting surface=gui.apple assertions=teams.membership.role-gated,teams.context.full-switch-local
    func testReturningToOverviewDropsSuspendedMemberAvatarPublication() async {
        let scope = SettingsTeamsTestScope(), service = SettingsTeamsCreationTestService()
        let controller = SettingsTeamsController(service: service, environment: scope.environment)
        await controller.load(accountID: scope.accountID)
        _ = await controller.continueCreation(name: "Chosen team")
        _ = await controller.create(name: "Chosen team", description: "")
        let gate = expectation(description: "member image suspended")
        service.avatarGate = gate
        let old = Task { await controller.loadManagement() }
        await fulfillment(of: [gate], timeout: 3)
        await controller.select(nil)
        service.avatarContinuation?.resume(returning: Data([1, 2, 3])); service.avatarContinuation = nil
        await old.value
        XCTAssertNil(controller.selectedID); XCTAssertTrue(controller.memberAvatarData.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.lifecycle.encrypted-profiled,teams.membership.role-gated
    func testAvatarUploadEncryptsMetadataAndHandlesSafetyWithoutPlaintextMultipartFields() async throws {
        let scope = SettingsTeamsTestScope()
        let team = makeSettingsTestTeam("avatar-team")
        let context = TeamWorkspaceSnapshot(accountID: scope.accountID, server: scope.server, scope: scope.scope, teamID: nil, epoch: 1)
        var status = "ok", rejectCount = 0
        var calls = 0
        let service = SettingsTeamsService(reader: SettingsTeamsTestReader(), avatarUpload: { jpeg, encrypted, id, fence, captured in
            calls += 1
            XCTAssertEqual(id, team.id); XCTAssertEqual(jpeg, Data([1, 2, 3]))
            XCTAssertEqual(fence.scope, scope.scope); XCTAssertEqual(captured.epoch, 1)
            XCTAssertFalse(encrypted.contains("image_url"))
            let text = try await CryptoManager.shared.decryptContent(base64String: encrypted, key: team.key)
            let metadata = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any])
            XCTAssertEqual(metadata["image_url"] as? String, "/v1/teams/avatar-team/profile-image")
            XCTAssertEqual(metadata["team_id"] as? String, team.id)
            XCTAssertEqual(metadata["mode"] as? String, "uploaded")
            let body = try APIClient.makeUploadBody(data: jpeg, filename: "team-profile.jpg", contentType: "image/jpeg", chatID: nil,
                boundary: "test-boundary", formFields: ["team_id": id, "encrypted_profile_image_metadata": encrypted])
            XCTAssertNil(body.range(of: Data("image_url".utf8)))
            XCTAssertNotNil(body.range(of: Data(encrypted.utf8)))
            return try JSONSerialization.data(withJSONObject: ["status": status, "reject_count": rejectCount])
        }, contextSnapshot: { context }, contextIsCurrent: { $0.scope == scope.scope })
        _ = try await service.uploadAvatar(team: team, jpeg: Data([1, 2, 3]), fence: scope.fence)
        status = "rejected"
        do { _ = try await service.uploadAvatar(team: team, jpeg: Data([1, 2, 3]), fence: scope.fence); XCTFail("Rejected safety result must not report success") }
        catch SettingsTeamsError.imageRejected { }
        rejectCount = 3
        do { _ = try await service.uploadAvatar(team: team, jpeg: Data([1, 2, 3]), fence: scope.fence); XCTFail("Third rejection must include the final warning") }
        catch SettingsTeamsError.imageRejectedFinalWarning { }
        status = "account_deleted"
        do { _ = try await service.uploadAvatar(team: team, jpeg: Data([1, 2, 3]), fence: scope.fence); XCTFail("Deleted account result must reach logout handling") }
        catch SettingsTeamsError.accountDeleted { }
        XCTAssertEqual(calls, 4)
        XCTAssertThrowsError(try APIClient.makeUploadBody(data: Data(), filename: "team.jpg", contentType: "image/jpeg", chatID: nil,
            boundary: "b", formFields: ["image_url": "plaintext forbidden"]))
    }

    // contract-test: supporting surface=gui.apple assertions=teams.lifecycle.encrypted-profiled
    func testAvatarRasterCropIsSquareAndStripsGPSExifBeforeUpload() throws {
        let colorSpace = try XCTUnwrap(CGColorSpace(name: CGColorSpace.sRGB))
        let context = try XCTUnwrap(CGContext(data: nil, width: 80, height: 40, bitsPerComponent: 8, bytesPerRow: 0,
            space: colorSpace, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue))
        context.setFillColor(CGColor(red: 0.3, green: 0.6, blue: 0.9, alpha: 1)); context.fill(CGRect(x: 0, y: 0, width: 80, height: 40))
        let raw = NSMutableData()
        let destination = try XCTUnwrap(CGImageDestinationCreateWithData(raw, UTType.jpeg.identifier as CFString, 1, nil))
        CGImageDestinationAddImage(destination, try XCTUnwrap(context.makeImage()), [
            kCGImagePropertyOrientation: 6,
            kCGImagePropertyGPSDictionary: [kCGImagePropertyGPSLatitude: 52.1, kCGImagePropertyGPSLongitude: 13.2],
            kCGImagePropertyExifDictionary: [kCGImagePropertyExifUserComment: "private location"]
        ] as CFDictionary)
        XCTAssertTrue(CGImageDestinationFinalize(destination))
        let jpeg = try SettingsTeamsService.avatarJPEG(raw as Data)
        let source = try XCTUnwrap(CGImageSourceCreateWithData(jpeg as CFData, nil))
        let properties = try XCTUnwrap(CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any])
        XCTAssertEqual(properties[kCGImagePropertyPixelWidth] as? Int, 340)
        XCTAssertEqual(properties[kCGImagePropertyPixelHeight] as? Int, 340)
        XCTAssertNil(properties[kCGImagePropertyGPSDictionary])
        if let exif = properties[kCGImagePropertyExifDictionary] as? [CFString: Any] { XCTAssertNil(exif[kCGImagePropertyExifUserComment]) }
        XCTAssertNil(jpeg.range(of: Data("private location".utf8)))
    }

    // contract-test: supporting surface=gui.apple assertions=teams.lifecycle.encrypted-profiled
    func testCreateUsesWrappedRandomTeamKeyAndEncryptedWebPayload() async throws {
        let scope = SettingsTeamsTestScope()
        let masterKey = SymmetricKey(size: .bits256)
        let reader = SettingsTeamsTestReader()
        var captured: [String: Any] = [:]
        let service = SettingsTeamsService(reader: reader, transport: { method, path, bytes, _ in
            XCTAssertEqual(method, .post)
            if path == "/v1/teams/name-approval" {
                let approval = try XCTUnwrap(JSONSerialization.jsonObject(with: XCTUnwrap(bytes)) as? [String: String])
                XCTAssertEqual(approval["name"], "encrypted workspace")
                return Data(#"{"approval_token":"scoped-test-approval"}"#.utf8)
            }
            XCTAssertEqual(path, "/v1/teams")
            captured = try XCTUnwrap(JSONSerialization.jsonObject(with: XCTUnwrap(bytes)) as? [String: Any])
            return try JSONSerialization.data(withJSONObject: ["team": ["team_id": captured["team_id"]!]])
        }, masterKey: { _ in masterKey })
        let created = try await service.create(name: "  Encrypted workspace  ", description: "Private description", fence: scope.fence)
        XCTAssertNil(reader.requestedID, "Create must reconstruct the acknowledged record without a failure-prone detail GET")
        XCTAssertEqual(captured["name_approval_token"] as? String, "scoped-test-approval")
        XCTAssertNil(captured["name"]); XCTAssertNil(captured["description"]); XCTAssertNil(captured["team_key"])
        let wrapped = try XCTUnwrap(captured["encrypted_team_key"] as? String)
        let key = try await CryptoManager.shared.unwrapChatKey(encryptedChatKeyBase64: wrapped, masterKey: masterKey)
        let encryptedName = try XCTUnwrap(captured["encrypted_name"] as? String)
        let name = try await CryptoManager.shared.decryptContent(base64String: encryptedName, key: key)
        let description = try await CryptoManager.shared.decryptContent(base64String: XCTUnwrap(captured["encrypted_description"] as? String), key: key)
        let zero = try await CryptoManager.shared.decryptContent(base64String: XCTUnwrap(captured["encrypted_zero_balance"] as? String), key: key)
        let profile = try await CryptoManager.shared.decryptContent(base64String: XCTUnwrap(captured["encrypted_profile_image_metadata"] as? String), key: key)
        XCTAssertEqual(name, "Encrypted workspace"); XCTAssertEqual(description, "Private description"); XCTAssertEqual(zero, "0")
        let metadata = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(profile.utf8)) as? [String: Any])
        XCTAssertEqual(metadata["icon_name"] as? String, "team")
        XCTAssertEqual(metadata["background_color"] as? String, "#4d73ff")
        XCTAssertEqual(captured["created_at"] as? Int, captured["updated_at"] as? Int)
        do {
            _ = try await CryptoManager.shared.decryptContent(base64String: encryptedName, key: masterKey)
            XCTFail("Account master key must not decrypt team metadata")
        } catch { }
    }

    // contract-test: supporting surface=gui.apple assertions=teams.membership.role-gated,teams.invites.fragment-key-web-flow
    func testInviteNormalizesDeliveryAddressEncryptsHintAndRejectsViewerBeforeTransport() async throws {
        let scope = SettingsTeamsTestScope()
        let team = makeSettingsTestTeam("team/encoded", role: .owner)
        var calls = 0
        let service = SettingsTeamsService(transport: { method, path, bytes, _ in
            calls += 1
            XCTAssertEqual(method, .post); XCTAssertEqual(path, "/v1/teams/team%2Fencoded/invites")
            let body = try XCTUnwrap(JSONSerialization.jsonObject(with: XCTUnwrap(bytes)) as? [String: Any])
            XCTAssertEqual(body["recipient_email"] as? String, "teammate@example.com")
            XCTAssertEqual(body["role"] as? String, "member")
            XCTAssertEqual((body["expires_at"] as? Int ?? 0) - (body["created_at"] as? Int ?? 0), 7 * 24 * 60 * 60)
            let hint = try await CryptoManager.shared.decryptContent(base64String: XCTUnwrap(body["encrypted_recipient_hint"] as? String), key: team.key)
            let hintObject = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(hint.utf8)) as? [String: String])
            XCTAssertEqual(hintObject, ["recipient_email": "teammate@example.com", "role": "member"])
            return Data(#"{"invite":{"delivery_status":"sent"}}"#.utf8)
        })
        let sent = try await service.invite(team: team, email: "  Teammate@Example.COM \n", fence: scope.fence)
        XCTAssertTrue(sent)
        do {
            _ = try await service.invite(team: makeSettingsTestTeam("viewer", role: .viewer), email: "teammate@example.com", fence: scope.fence)
            XCTFail("Viewer may not create invites")
        } catch SettingsTeamsError.permissionDenied { }
        XCTAssertEqual(calls, 1)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.invites.fragment-key-web-flow
    func testSecureInviteFragmentUnwrapsExactTeamKeyWithWebHKDFContract() async throws {
        let scope = SettingsTeamsTestScope()
        let team = makeSettingsTestTeam("shared", role: .owner)
        var captured: [String: Any] = [:]
        let service = SettingsTeamsService(transport: { _, _, bytes, _ in
            captured = try XCTUnwrap(JSONSerialization.jsonObject(with: XCTUnwrap(bytes)) as? [String: Any])
            return try JSONSerialization.data(withJSONObject: ["invite": ["invite_id": captured["invite_id"]!, "status": "created"]])
        })
        let result = try await service.invitation(team: team, email: "User@Example.COM", fence: scope.fence)
        let url = try XCTUnwrap(result.url)
        XCTAssertFalse(result.delivered)
        let fragment = try XCTUnwrap(url.fragment)
        XCTAssertTrue(fragment.hasPrefix("key="))
        var base64 = String(fragment.dropFirst(4)).replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        base64 += String(repeating: "=", count: (4 - base64.count % 4) % 4)
        let secret = try XCTUnwrap(Data(base64Encoded: base64))
        XCTAssertEqual(secret.count, 32)
        let inviteID = try XCTUnwrap(captured["invite_id"] as? String)
        let origin = scope.server.webBaseURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        // Build WebCrypto's exact big-endian length-prefixed info independently.
        var info = Data()
        for value in ["user@example.com", inviteID, "shared", origin] {
            let bytes = Array(value.utf8); let count = UInt32(bytes.count)
            info.append(contentsOf: [UInt8((count >> 24) & 255), UInt8((count >> 16) & 255), UInt8((count >> 8) & 255), UInt8(count & 255)])
            info.append(contentsOf: bytes)
        }
        let key = HKDF<SHA256>.deriveKey(inputKeyMaterial: SymmetricKey(data: secret),
            salt: Data(SHA256.hash(data: Data("openmates:team-invite:v1".utf8))), info: info, outputByteCount: 32)
        let encrypted = try XCTUnwrap(Data(base64Encoded: XCTUnwrap(captured["encrypted_invite_team_key"] as? String)))
        let opened = try AES.GCM.open(AES.GCM.SealedBox(combined: encrypted), using: key)
        XCTAssertEqual(opened, team.key.withUnsafeBytes { Data($0) })
        let context = try XCTUnwrap(captured["invite_key_kdf_context"] as? [String: Any])
        XCTAssertEqual(context["origin"] as? String, origin)
        XCTAssertEqual(context["team_id"] as? String, team.id)
        XCTAssertEqual(context["invite_id"] as? String, inviteID)
        XCTAssertNil(captured["secret"]); XCTAssertNil(captured["invite_url"]); XCTAssertNil(captured["team_key"])
        let posted = String(decoding: try JSONSerialization.data(withJSONObject: captured), as: UTF8.self)
        XCTAssertFalse(posted.contains(String(fragment.dropFirst(4))))
    }

    // contract-test: supporting surface=gui.apple assertions=teams.membership.role-gated
    func testManagementRejectsViewerAndOwnerRoleTransferBeforeMutation() async throws {
        let scope = SettingsTeamsTestScope()
        let reader = SettingsTeamsTestReader()
        var mutations = 0
        let service = SettingsTeamsService(reader: reader, transport: { _, _, _, _ in mutations += 1; return Data(#"{"success":true}"#.utf8) })
        let ownerMember = SettingsTeamMember(id: "owner", userID: "owner", name: "Owner", role: .owner, status: "active")
        do {
            try await service.changeRole(team: makeSettingsTestTeam("team", role: .viewer), member: ownerMember, role: .member, fence: scope.fence)
            XCTFail("Viewer must not change roles")
        } catch SettingsTeamsError.permissionDenied { }
        do {
            try await service.removeMember(team: makeSettingsTestTeam("team"), member: ownerMember, fence: scope.fence)
            XCTFail("Owner removal must not be offered through member management")
        } catch SettingsTeamsError.invalidMember { }
        XCTAssertEqual(mutations, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.lifecycle.encrypted-profiled,teams.membership.role-gated,storage.surface.semantic-parity
    func testBillingUsesVersionedAuthoritativeBalanceAndCountsOnlyTeamMemories() async throws {
        let scope = SettingsTeamsTestScope()
        let team = makeSettingsTestTeam("one", role: .owner)
        let encrypted = try await CryptoManager.shared.encryptWithMasterKey("9", masterKey: team.key)
        var paths: [String] = []
        let service = SettingsTeamsService(transport: { _, path, _, _ in
            paths.append(path)
            let result: [String: Any] = path.hasSuffix("billing")
                ? ["billing": ["balance_credits": 72, "version": 3, "encrypted_balance": encrypted]]
                : ["memories": [["id": "team-memory-1"], ["id": "team-memory-2"]]]
            return try JSONSerialization.data(withJSONObject: result)
        })
        let result = try await service.details(team: team, fence: scope.fence)
        XCTAssertEqual(result, SettingsTeamDetails(credits: 72, memoryCount: 2, balanceVersion: 3))
        XCTAssertEqual(paths, ["/v1/teams/one/billing", "/v1/teams/one/memories"])
    }

    // contract-test: supporting surface=gui.apple assertions=teams.membership.role-gated
    func testMemberAndViewerDetailsSkipForbiddenBillingRead() async throws {
        let scope = SettingsTeamsTestScope()
        var paths: [String] = []
        let service = SettingsTeamsService(transport: { _, path, _, _ in
            paths.append(path)
            XCTAssertTrue(path.hasSuffix("/memories"))
            return Data(#"{"memories":[{"id":"readable-team-memory"}]}"#.utf8)
        })
        for role in [TeamWorkspaceRole.member, .viewer] {
            let result = try await service.details(team: makeSettingsTestTeam(role.rawValue, role: role), fence: scope.fence)
            XCTAssertEqual(result, SettingsTeamDetails(credits: 0, memoryCount: 1))
        }
        XCTAssertEqual(paths, ["/v1/teams/member/memories", "/v1/teams/viewer/memories"])
    }

    // contract-test: supporting surface=gui.apple assertions=teams.context.full-switch-local
    func testFoundationReaderPinsIdentityAndRejectsLateChangedAccountResponse() async throws {
        let scope = SettingsTeamsTestScope()
        let fence = scope.fence
        let reader = TeamWorkspaceService(transport: { path, pinned in
            XCTAssertEqual(path, "/v1/teams")
            XCTAssertEqual(pinned.accountID, "settings-test-account")
            XCTAssertEqual(pinned.scope, fence.scope); XCTAssertEqual(pinned.server, .development)
            scope.accountID = "another-account"
            return Data(#"{"teams":[]}"#.utf8)
        })
        do {
            _ = try await reader.listTeams(fence: fence)
            XCTFail("Reader must reject a response after account changes")
        } catch TeamWorkspaceError.staleContext { }
    }

    // contract-test: supporting surface=gui.apple assertions=teams.context.full-switch-local
    func testStaleFenceCannotStartTransport() async throws {
        let scope = SettingsTeamsTestScope()
        let fence = scope.fence
        scope.accountID = "another-account"
        var calls = 0
        let service = SettingsTeamsService(transport: { _, _, _, _ in calls += 1; return Data() })
        do {
            _ = try await service.details(team: makeSettingsTestTeam("one"), fence: fence)
            XCTFail("Changed account must invalidate team operations")
        } catch TeamWorkspaceError.staleContext { }
        XCTAssertEqual(calls, 0)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.context.full-switch-local
    func testControllerAccountResetSuppressesOldListAndKeys() async {
        let scope = SettingsTeamsTestScope()
        let service = SettingsTeamsTestService()
        service.suspendList = true
        let controller = SettingsTeamsController(service: service, environment: scope.environment)
        let task = Task { await controller.load(accountID: scope.accountID) }
        for _ in 0..<100 where service.listContinuation == nil { await Task.yield() }
        XCTAssertNotNil(service.listContinuation)
        scope.accountID = "another-account"; scope.scope = UUID(); controller.reset()
        service.listContinuation?.resume(returning: [makeSettingsTestTeam("old-private-team")])
        await task.value
        XCTAssertTrue(controller.teams.isEmpty); XCTAssertNil(controller.selected); XCTAssertFalse(controller.loading)
    }

    // contract-test: supporting surface=gui.apple assertions=teams.context.full-switch-local,settings-ui.navigation.parent-return
    func testReturningToOverviewSuppressesPendingTeamDetail() async {
        let scope = SettingsTeamsTestScope()
        let service = SettingsTeamsTestService()
        service.teams = [makeSettingsTestTeam("one")]
        let controller = SettingsTeamsController(service: service, environment: scope.environment)
        await controller.load(accountID: scope.accountID)
        service.suspendDetails = true
        let task = Task { await controller.select("one") }
        for _ in 0..<100 where service.detailContinuation == nil { await Task.yield() }
        XCTAssertNotNil(service.detailContinuation)
        await controller.select(nil)
        service.detailContinuation?.resume(returning: SettingsTeamDetails(credits: 123, memoryCount: 3))
        await task.value
        XCTAssertNil(controller.selectedID); XCTAssertNil(controller.details); XCTAssertFalse(controller.loading)
    }
}

@MainActor private final class SettingsTeamsTestScope {
    var accountID = "settings-test-account"
    var scope = UUID()
    var server = ServerProfile.development
    var environment: TeamWorkspaceEnvironment {
        TeamWorkspaceEnvironment(currentAccountID: { self.accountID }, scopeGeneration: { self.scope }, serverProfile: { self.server })
    }
    var fence: TeamWorkspaceFence { TeamWorkspaceFence(accountID: accountID, environment: environment) }
}

@MainActor private final class SettingsTeamsTestReader: TeamWorkspaceServing {
    var requestedID: String?
    var team: TeamWorkspaceTeam?
    var offlineDetails = false
    var nextDetailError: Error?
    func cachedTeams(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam] { team.map { [$0] } ?? [] }
    func listTeams(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam] { [] }
    func getTeam(_ id: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam {
        requestedID = id
        if let error = nextDetailError { nextDetailError = nil; throw error }
        if offlineDetails { throw URLError(.notConnectedToInternet) }
        return team ?? makeSettingsTestTeam(id)
    }
}

@MainActor private final class SettingsTeamsTestService: SettingsTeamsServing {
    var teams: [TeamWorkspaceTeam] = []
    var suspendList = false
    var suspendDetails = false
    var listContinuation: CheckedContinuation<[TeamWorkspaceTeam], Never>?
    var detailContinuation: CheckedContinuation<SettingsTeamDetails, Never>?
    func list(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam] {
        if suspendList { return await withCheckedContinuation { listContinuation = $0 } }
        return teams
    }
    func details(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws -> SettingsTeamDetails {
        if suspendDetails { return await withCheckedContinuation { detailContinuation = $0 } }
        return SettingsTeamDetails(credits: 0, memoryCount: 0)
    }
    func create(name: String, description: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam { makeSettingsTestTeam("created") }
    func invite(team: TeamWorkspaceTeam, email: String, fence: TeamWorkspaceFence) async throws -> Bool { true }
}

private func makeSettingsTestTeam(_ id: String, role: TeamWorkspaceRole = .owner) -> TeamWorkspaceTeam {
    TeamWorkspaceTeam(id: id, name: "Synthetic team", description: "Test state", role: role, status: "active",
        profileImageMetadata: .generated, zeroBalance: 0, createdAt: 1, updatedAt: 1, key: SymmetricKey(size: .bits256))
}

@MainActor private final class SettingsTeamsCreationTestService: SettingsTeamsServing {
    var checkedNames: [String] = [], createCalls = 0, uploadedIDs: [String] = []
    var rejectUpload = false
    var nameGate: XCTestExpectation?, avatarGate: XCTestExpectation?
    var nameContinuation: CheckedContinuation<Void, Never>?
    var avatarContinuation: CheckedContinuation<Data?, Never>?
    func list(fence: TeamWorkspaceFence) async throws -> [TeamWorkspaceTeam] { [] }
    func checkCreationName(_ name: String, fence: TeamWorkspaceFence) async throws {
        checkedNames.append(name)
        if let gate = nameGate { await withCheckedContinuation { nameContinuation = $0; gate.fulfill() } }
    }
    func createProfiledAvatar(name: String, description: String, memberName: String?, icon: String, color: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam {
        createCalls += 1
        return TeamWorkspaceTeam(id: "created-once", name: name, description: description, role: .owner, status: "active",
            profileImageMetadata: .init(version: 1, mode: "generated", iconName: icon, iconColor: "#ffffff", backgroundColor: color),
            zeroBalance: 0, createdAt: 1, updatedAt: 1, key: SymmetricKey(size: .bits256))
    }
    func create(name: String, description: String, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam { makeSettingsTestTeam("created-once") }
    func uploadAvatar(team: TeamWorkspaceTeam, jpeg: Data, fence: TeamWorkspaceFence) async throws -> TeamWorkspaceTeam {
        uploadedIDs.append(team.id)
        if rejectUpload { throw SettingsTeamsError.imageRejected }
        return team
    }
    func details(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws -> SettingsTeamDetails { .init(credits: 0, memoryCount: 0) }
    func management(team: TeamWorkspaceTeam, fence: TeamWorkspaceFence) async throws -> SettingsTeamManagement {
        .init(members: [.init(id: "portrait-member", userID: "portrait-member", name: "Member", role: .member, status: "active")], invites: [], security: .init())
    }
    func memberAvatar(team: TeamWorkspaceTeam, member: SettingsTeamMember, fence: TeamWorkspaceFence) async throws -> Data? {
        if let gate = avatarGate { return await withCheckedContinuation { avatarContinuation = $0; gate.fulfill() } }
        return nil
    }
    func invite(team: TeamWorkspaceTeam, email: String, fence: TeamWorkspaceFence) async throws -> Bool { true }
}

private func testMemberAvatarJPEG() throws -> Data {
    let colorSpace = try XCTUnwrap(CGColorSpace(name: CGColorSpace.sRGB))
    let context = try XCTUnwrap(CGContext(data: nil, width: 2, height: 2, bitsPerComponent: 8, bytesPerRow: 0,
        space: colorSpace, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue))
    let data = NSMutableData()
    let destination = try XCTUnwrap(CGImageDestinationCreateWithData(data, UTType.jpeg.identifier as CFString, 1, nil))
    CGImageDestinationAddImage(destination, try XCTUnwrap(context.makeImage()), nil)
    XCTAssertTrue(CGImageDestinationFinalize(destination)); return data as Data
}
