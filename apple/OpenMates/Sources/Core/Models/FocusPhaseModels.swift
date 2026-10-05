// Web counterparts: types/focusPhases.ts and settings/FocusModePhases.svelte.
// Specification: specifications/features/focus-modes/specification.yml
// Assertions: focus-modes.phases, focus-modes.history-events, focus-modes.project-authoring-click
// Specification: specifications/features/rules/specification.yml — rules.transparency.applied-set
// Specification: specifications/features/chats/specification.yml — chats.direction.reviewed-correction
// Web source: frontend/packages/ui/src/utils/agentContextEvents.ts
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


/// Parsing persisted receipts is inert: it grants no Focus or authoring authority.
struct AppliedRuleGuide: Identifiable, Equatable, Sendable {
    let id: String
    let title: String
    let source: String
    let revision: String
    let body: String
    let appID: String?
    let projectID: String?
}

struct ProjectAuthoringRecommendation: Identifiable, Equatable, Sendable {
    let id: String
    let chatID: String
    let projectID: String
    let kind: String
    let action: String
    let targetID: String?
    let expectedRevision: String?
    let title: String?
    let expiresAt: TimeInterval?

    var isExpired: Bool { expiresAt.map { $0 <= Date().timeIntervalSince1970 } ?? false }
    var localizationKey: String { "rules.\(action)_\(kind)" }

    static func parse(_ entry: [String: Any]) -> Self? {
        guard let id = entry["recommendation_id"] as? String, !id.isEmpty,
              let chatID = entry["chat_id"] as? String, !chatID.isEmpty,
              let projectID = entry["project_id"] as? String, !projectID.isEmpty,
              let kind = entry["kind"] as? String, ["focus", "workflow"].contains(kind),
              let action = entry["action"] as? String, ["create", "update"].contains(action),
              entry["expires_at"] == nil || entry["expires_at"] is NSNumber,
              entry["expected_revision"] == nil || entry["expected_revision"] is NSNull || entry["expected_revision"] is String,
              entry["target_id"] == nil || entry["target_id"] is NSNull || entry["target_id"] is String else { return nil }
        return Self(id: id, chatID: chatID, projectID: projectID, kind: kind, action: action,
                    targetID: entry["target_id"] as? String, expectedRevision: entry["expected_revision"] as? String,
                    title: entry["title"] as? String, expiresAt: (entry["expires_at"] as? NSNumber)?.doubleValue)
    }
}

enum AgentContextEvent: Equatable, Sendable {
    case rulesLoaded(setKey: String, rules: [AppliedRuleGuide])
    case directionCorrection(notice: String, instruction: String, deliveryID: String)
    case authoring([ProjectAuthoringRecommendation])

    static func parse(_ text: String) -> Self? {
        guard text.count <= 100_000, let data = text.data(using: .utf8),
              let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        return parse(value)
    }

    static func parse(_ value: [String: Any]) -> Self? {
        switch value["type"] as? String {
        case "rules_loaded":
            guard let rows = value["rules"] as? [[String: Any]], !rows.isEmpty, rows.count <= 24,
                  value["count"] as? Int == rows.count, let key = value["set_key"] as? String else { return nil }
            var guides: [AppliedRuleGuide] = []
            var identities = Set<String>()
            for row in rows {
                guard let id = row["id"] as? String, identities.insert(id).inserted,
                      let title = row["title"] as? String, !title.isEmpty,
                      let body = row["body"] as? String, !body.isEmpty,
                      let revision = row["revision"] as? String,
                      revision.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil,
                      let source = row["source"] as? String, ["app", "personal", "project"].contains(source) else { return nil }
                guides.append(AppliedRuleGuide(id: id, title: title, source: source, revision: revision, body: body,
                    appID: row["app_id"] as? String, projectID: row["project_id"] as? String))
            }
            return .rulesLoaded(setKey: key, rules: guides)
        case "chat_direction_correction":
            guard let notice = value["notice"] as? String, !notice.isEmpty,
                  let instruction = value["instruction"] as? String, !instruction.isEmpty,
                  let id = value["delivery_id"] as? String, !id.isEmpty else { return nil }
            return .directionCorrection(notice: notice, instruction: instruction, deliveryID: id)
        case "project_authoring_recommendation":
            return ProjectAuthoringRecommendation.parse(value).map { .authoring([$0]) }
        case "project_authoring_recommendations":
            guard let rows = value["recommendations"] as? [[String: Any]] else { return nil }
            let recommendations = rows.compactMap(ProjectAuthoringRecommendation.parse)
            guard !recommendations.isEmpty, recommendations.count <= 16 else { return nil }
            return .authoring(recommendations)
        default: return nil
        }
    }
}

/// A live receipt must belong to this chat and have a deterministic persisted ID.
struct AppliedChatContextReceipt {
    let chatID: String
    let messageID: String
    let createdAt: Int
    let content: String

    static func parse(_ payload: [String: Any]) -> Self? {
        guard let chatID = payload["chat_id"] as? String, UUID(uuidString: chatID) != nil,
              let event = payload["event"] as? [String: Any], event["chat_id"] as? String == chatID,
              AgentContextEvent.parse(event) != nil,
              let id = event["event_id"] as? String, UUID(uuidString: id) != nil,
              let createdAt = event["created_at"] as? Int, createdAt > 0,
              let data = try? JSONSerialization.data(withJSONObject: event, options: [.sortedKeys]),
              let content = String(data: data, encoding: .utf8), content.count <= 100_000 else { return nil }
        return Self(chatID: chatID, messageID: id, createdAt: createdAt, content: content)
    }
}
