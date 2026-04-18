// AuthModels unit tests — validates decoding of auth responses and user profiles.

import XCTest
@testable import OpenMates

final class AuthModelsTests: XCTestCase {

    func testUserProfileDecodes() throws {
        let json = """
        {
            "id": "user-123",
            "username": "testuser",
            "email": "test@openmates.org",
            "credits": 42.5,
            "language": "en",
            "darkmode": false,
            "timezone": "Europe/Berlin",
            "last_opened": null,
            "profile_image_url": null,
            "is_admin": false
        }
        """
        let data = json.data(using: .utf8)!
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let profile = try decoder.decode(UserProfile.self, from: data)

        XCTAssertEqual(profile.id, "user-123")
        XCTAssertEqual(profile.username, "testuser")
        XCTAssertEqual(profile.email, "test@openmates.org")
        XCTAssertEqual(profile.credits, 42.5)
        XCTAssertEqual(profile.isAdmin, false)
    }

    func testUserProfileDecodesMinimalFields() throws {
        let json = """
        {
            "id": "user-minimal",
            "username": "minimal"
        }
        """
        let data = json.data(using: .utf8)!
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let profile = try decoder.decode(UserProfile.self, from: data)

        XCTAssertEqual(profile.id, "user-minimal")
        XCTAssertNil(profile.credits)
        XCTAssertNil(profile.email)
        XCTAssertNil(profile.isAdmin)
    }

    func testLoginResponseDecodes() throws {
        let json = """
        {
            "success": true,
            "tfa_required": false,
            "auth_session": null,
            "needs_device_verification": false,
            "device_verification_type": null,
            "encrypted_master_key": "abc123",
            "key_iv": "iv123",
            "user_email_salt": "salt123"
        }
        """
        let data = json.data(using: .utf8)!
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let response = try decoder.decode(LoginResponse.self, from: data)

        XCTAssertTrue(response.success)
        XCTAssertEqual(response.tfaRequired, false)
        XCTAssertEqual(response.encryptedMasterKey, "abc123")
    }

    func testLookupResponseDecodes() throws {
        let json = """
        {
            "available_login_methods": ["password", "passkey"],
            "tfa_enabled": true,
            "tfa_app_name": "Authy"
        }
        """
        let data = json.data(using: .utf8)!
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let response = try decoder.decode(LookupResponse.self, from: data)

        XCTAssertEqual(response.availableLoginMethods, [.password, .passkey])
        XCTAssertTrue(response.tfaEnabled)
        XCTAssertEqual(response.tfaAppName, "Authy")
    }

    func testSessionResponseDecodes() throws {
        let json = """
        {
            "is_authenticated": true,
            "user": {
                "id": "user-sess",
                "username": "sessuser"
            },
            "auth_session": null,
            "needs_device_verification": false,
            "device_verification_type": null
        }
        """
        let data = json.data(using: .utf8)!
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let response = try decoder.decode(SessionResponse.self, from: data)

        XCTAssertTrue(response.isAuthenticated)
        XCTAssertEqual(response.user?.username, "sessuser")
    }
}
