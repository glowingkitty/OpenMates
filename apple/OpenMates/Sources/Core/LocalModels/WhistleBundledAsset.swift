// Immutable bundled Whistle evaluation asset; never downloaded or copied to Documents.
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.privacy-context
import CryptoKit
import Foundation

enum WhistleBundledAsset {
    static let repositoryRevision = "741118687e1f008f06d1351a402a731274789790"
    static let runtimeRevision = "3391a1007e7db31d2fe5c69c734bbe93a9c1ce79"
    static let sizeBytes = 16_919_407
    static let sha256 = "b6e02f048568ac5d01a2042556c658061e699acbc0aa2a1439f52f3d461dffeb"
    static let minimumOS = "26.2"

    static func modelURL(in bundle: Bundle = .main) throws -> URL {
        guard let url = bundle.url(forResource: "whistle", withExtension: "cact", subdirectory: "Whistle") else {
            throw LocalSpeechRuntimeError.invalidAssets
        }
        return url
    }

    // Runs on the native worker queue before the first load. Keep mapped data only
    // for needle_load's call, following the pinned upstream Python binding's lifetime.
    static func verifiedModelBytes(at url: URL) throws -> Data {
        do {
            let values = try url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey])
            guard values.isRegularFile == true, values.isSymbolicLink != true, values.fileSize == sizeBytes else {
                throw LocalSpeechRuntimeError.invalidAssets
            }
            let bytes = try Data(contentsOf: url, options: .alwaysMapped)
            guard bytes.count == sizeBytes,
                  SHA256.hash(data: bytes).map({ String(format: "%02x", $0) }).joined() == sha256 else {
                throw LocalSpeechRuntimeError.invalidAssets
            }
            return bytes
        } catch { throw LocalSpeechRuntimeError.invalidAssets }
    }
}
