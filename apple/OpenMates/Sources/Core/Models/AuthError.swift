// Shared native auth errors.
// Kept outside AuthManager so lightweight targets such as the standalone Watch
// app can use the same auth runtime without importing the full iOS/macOS auth
// view-model dependency graph.
// Error copy matches the existing native auth flow behavior.

import Foundation

enum AuthError: LocalizedError {
    case tfaRequired
    case invalidCredentials
    case deviceVerificationRequired
    case missingAuthData
    case invalidTwoFactorCode

    var errorDescription: String? {
        switch self {
        case .tfaRequired: return "Two-factor authentication required"
        case .invalidCredentials: return "Invalid email or password"
        case .deviceVerificationRequired: return "Device verification required"
        case .missingAuthData: return "Authentication data not found. Please try logging in again."
        case .invalidTwoFactorCode: return "The two-factor code is wrong or expired"
        }
    }
}
