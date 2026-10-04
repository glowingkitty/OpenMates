// Web counterparts: types/focusPhases.ts and settings/FocusModePhases.svelte.
// Specification: specifications/features/focus-modes/specification.yml
// Assertions: focus-modes.phases, focus-modes.history-events
import Foundation
import Yams

struct FocusPhaseRequirement: Codable, Identifiable, Sendable {
    let id: String
    let text: String
    let type: String?
}
struct FocusPhaseDefinition: Codable, Identifiable, Sendable {
    let id: String
    let title: String
    let instructions: String
    let requirements: [FocusPhaseRequirement]
    static func fromInstruction(_ instruction: String) -> [FocusPhaseDefinition] {
        guard instruction.hasPrefix("---\n"),
              let end = instruction.range(of: "\n---", range: instruction.index(instruction.startIndex, offsetBy: 4)..<instruction.endIndex) else { return [] }
        let yaml = String(instruction[instruction.index(instruction.startIndex, offsetBy: 4)..<end.lowerBound])
        struct Definition: Decodable { let phases_version: Int; let phases: [FocusPhaseDefinition] }
        guard let definition = try? YAMLDecoder().decode(Definition.self, from: yaml), definition.phases_version == 1,
              !definition.phases.isEmpty,
              Set(definition.phases.map(\.id)).count == definition.phases.count else { return [] }
        return definition.phases
    }
}
struct FocusPhaseEvent: Codable, Identifiable, Sendable {
    let type: String
    let eventId: String
    let chatId: String
    let focusId: String
    let runId: String
    let version: Int
    let previousPhaseId: String?
    let phaseId: String
    let phaseTitle: String
    let direction: String
    let createdAt: Int
    let projectId: String?
    var id: String { eventId }
    var detailPath: String? {
        if let projectId, UUID(uuidString: projectId) != nil { return "projects/\(projectId)" }
        let parts = focusId.split(separator: "-", maxSplits: 1).map(String.init)
        guard parts.count == 2, parts.allSatisfy({ $0.range(of: "^[a-z][a-z0-9_-]*$", options: .regularExpression) != nil }) else { return nil }
        return "apps/\(parts[0])/focus/\(parts[1])"
    }
    static func parse(_ text: String) -> FocusPhaseEvent? {
        guard text.utf8.count < 16_384, let data = text.data(using: .utf8) else { return nil }
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        guard let event = try? decoder.decode(Self.self, from: data), event.type == "focus_phase_changed",
              ["forward", "backward"].contains(event.direction), !event.phaseTitle.isEmpty, event.phaseTitle.count <= 200 else { return nil }
        return event
    }
}
struct FocusPhaseState: Codable, Sendable {
    let schemaVersion: Int
    let chatId: String
    let focusId: String
    let revision: String
    let runId: String
    let version: Int
    let phaseId: String
    let complete: Bool
    let enteredAfterMessageId: String?
    let rewindTurn: String?
    let evaluatedBoundaries: [String]
    let transitions: [FocusPhaseEvent]
}
struct FocusPhasesUpdatedPayload: Decodable {
    let chatId: String
    let states: [String: FocusPhaseState]
}
