// Process-global Needle speech API; all native calls are serialized off the UI executor.
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.recording.lifecycle, message-input.privacy-context
import Foundation
#if OM_WHISTLE_NATIVE && canImport(OMWhistleBridge)
import OMWhistleBridge
#endif

struct WhistleRuntimeCapability: Equatable, Sendable {
    let nativeAvailable: Bool
    let modelResident: Bool
    let reclaimsModelOnSessionEnd: Bool
    let nativeScratchErasureVerified: Bool
    let minimumOS: String
}

protocol WhistleNativeEngine: Sendable {
    func load(modelURL: URL) async throws
    func transcribe(_ samples: [Float]) async throws -> String
    func endSession() async
    func capability() async -> WhistleRuntimeCapability
}

/// A single engine and queue per process. Never instantiate a second C API owner.
final class WhistleNativeBridge: WhistleNativeEngine, @unchecked Sendable {
    static let shared = WhistleNativeBridge()
    private let queue = DispatchQueue(label: "org.openmates.whistle.native", qos: .userInitiated)
    private init() {}

    private func perform<T: Sendable>(_ work: @escaping @Sendable () throws -> T) async throws -> T {
        try await withCheckedThrowingContinuation { continuation in
            queue.async {
                do { continuation.resume(returning: try work()) }
                catch { continuation.resume(throwing: error) }
            }
        }
    }

    private static var available: Bool {
        #if OM_WHISTLE_NATIVE && canImport(OMWhistleBridge) && (os(iOS) || os(watchOS))
        if #available(iOS 26.2, watchOS 26.2, *) { return true }
        #endif
        return false
    }

    func load(modelURL: URL) async throws {
        guard Self.available else { throw LocalSpeechRuntimeError.unavailableRuntime }
        try await perform { () throws -> Void in
            #if OM_WHISTLE_NATIVE && canImport(OMWhistleBridge)
            if om_whistle_model_resident() != 0 { return }
            let bytes = try WhistleBundledAsset.verifiedModelBytes(at: modelURL)
            let result = bytes.withUnsafeBytes { buffer in
                om_whistle_load(buffer.bindMemory(to: UInt8.self).baseAddress, buffer.count)
            }
            guard result == 0 else { throw LocalSpeechRuntimeError.invalidAssets }
            #else
            throw LocalSpeechRuntimeError.unavailableRuntime
            #endif
        }
    }

    func transcribe(_ samples: [Float]) async throws -> String {
        guard Self.available else { throw LocalSpeechRuntimeError.unavailableRuntime }
        return try await perform {
            #if OM_WHISTLE_NATIVE && canImport(OMWhistleBridge)
            // Fixed capacity bounds output memory; errors/truncation never return partial text.
            var output = [CChar](repeating: 0, count: WhistleNativeOutput.maximumBytes)
            defer { output.withUnsafeMutableBytes { $0.initializeMemory(as: UInt8.self, repeating: 0) } }
            let result = samples.withUnsafeBufferPointer { pcm in
                output.withUnsafeMutableBufferPointer { text in
                    om_whistle_transcribe(pcm.baseAddress, Int32(pcm.count), text.baseAddress, Int32(text.count))
                }
            }
            return try output.withUnsafeBytes {
                try WhistleNativeOutput.parse(returnCode: result, nulTerminatedJSON: Data($0))
            }
            #else
            throw LocalSpeechRuntimeError.unavailableRuntime
            #endif
        }
    }

    func endSession() async {
        _ = try? await perform {
            #if OM_WHISTLE_NATIVE && canImport(OMWhistleBridge)
            om_whistle_end_session()
            #endif
        }
    }

    func capability() async -> WhistleRuntimeCapability {
        let resident = (try? await perform {
            #if OM_WHISTLE_NATIVE && canImport(OMWhistleBridge)
            return om_whistle_model_resident() != 0
            #else
            return false
            #endif
        }) ?? false
        return .init(nativeAvailable: Self.available, modelResident: resident,
                     reclaimsModelOnSessionEnd: false, nativeScratchErasureVerified: false,
                     minimumOS: WhistleBundledAsset.minimumOS)
    }
}
