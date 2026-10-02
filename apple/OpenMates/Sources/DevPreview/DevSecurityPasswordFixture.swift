// Isolated UI evidence for the production password form's rejected-commit path.
// No owner API calls, persistent state, credentials or cryptography are used.
#if DEBUG
import Foundation

struct DevSecurityPasswordFixture {
    let commitStatus: Int

    static var current: Self? {
        let arguments = ProcessInfo.processInfo.arguments
        guard arguments.contains("--ui-test-account-settings-fixture"),
              let marker = arguments.firstIndex(of: "--ui-test-password-commit-status"),
              marker + 1 < arguments.count,
              let status = Int(arguments[marker + 1]), [401, 428, 503].contains(status) else { return nil }
        return Self(commitStatus: status)
    }

    var challenge: SensitiveEmailChallenge {
        .init(success: true, challengeId: "synthetic-ui-challenge", expiresIn: 60,
              passwordChallengeId: nil, passwordNonce: nil)
    }

    @MainActor
    func rejectCommit() throws {
        throw AccountSecurityError.passwordUpdateFailure(
            APIError.httpError(status: commitStatus, message: "Synthetic password commit rejection"))
    }
}
#endif
