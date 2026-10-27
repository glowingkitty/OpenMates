// Bounded native result boundary. Never return partial text or upstream error details.
// Specification: specifications/features/message-input/specification.yml
// Assertions: message-input.privacy-context
import Foundation

enum WhistleNativeOutput {
    static let maximumBytes = 262_144
    private struct Transcript: Decodable { let text: String }

    static func parse(returnCode: Int32, nulTerminatedJSON output: Data) throws -> String {
        guard returnCode >= 0, !output.isEmpty, output.count <= maximumBytes,
              let end = output.firstIndex(of: 0), end > output.startIndex,
              let transcript = try? JSONDecoder().decode(Transcript.self, from: output.prefix(upTo: end)) else {
            throw LocalSpeechRuntimeError.invalidOutput
        }
        return transcript.text.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
