// Uses one disposable, random Keychain item to verify the same signed shared
// group that the containing app and share extension use. No account keys move.
import Foundation
import Security
import XCTest
@testable import OpenMates

final class KeychainSharingTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=sync.access.first-party-authenticated
    func testKeychainUsesConfiguredSharedGroupIncludingSimulator() throws {
        let group = try XCTUnwrap(Bundle.main.object(forInfoDictionaryKey: "OpenMatesKeychainAccessGroup") as? String)
        XCTAssertFalse(group.isEmpty)
        XCTAssertFalse(group.contains("$("))
        XCTAssertEqual(KeychainHelper.queryAccessGroup, group)
    }

    // contract-test: supporting surface=gui.apple assertions=sync.access.first-party-authenticated
    func testSyntheticItemIsReadableThroughExplicitSharedGroupAndHelper() throws {
        let group = try XCTUnwrap(KeychainHelper.queryAccessGroup)
        let key = "openmates.share-keychain-test.\(UUID().uuidString)"
        let data = Data([0x4f, 0x4d, 0x53, 0x48])
        try KeychainHelper.save(key: key, data: data)
        defer { try? KeychainHelper.delete(key: key) }
        let query: [CFString: Any] = [
            kSecClass: kSecClassGenericPassword,
            kSecAttrService: "org.openmates.app",
            kSecAttrAccount: key,
            kSecAttrAccessGroup: group,
            kSecAttrSynchronizable: kCFBooleanFalse!,
            kSecReturnData: kCFBooleanTrue!,
            kSecMatchLimit: kSecMatchLimitOne
        ]
        var result: AnyObject?
        XCTAssertEqual(SecItemCopyMatching(query as CFDictionary, &result), errSecSuccess)
        XCTAssertEqual(result as? Data, data)
        XCTAssertEqual(try KeychainHelper.load(key: key), data)
    }
}
