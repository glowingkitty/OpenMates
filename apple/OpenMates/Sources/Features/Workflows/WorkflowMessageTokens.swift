// Storage syntax and display segments for typed Workflow output references.
// Web source: frontend/packages/ui/src/components/workflows/workflowMessageTokens.ts

import Foundation

struct WorkflowMessageOutput: Identifiable, Sendable {
    let reference: String
    let label: String
    let appId: String?

    var id: String { reference }
}

enum WorkflowMessageSegment: Equatable, Sendable {
    case text(String)
    case output(reference: String, label: String, syntax: String, appId: String?)

    var storageText: String {
        switch self {
        case .text(let text): text
        case .output(_, _, let syntax, _): syntax
        }
    }
}

@MainActor
enum WorkflowMessageTokens {
    private static let pattern = try! NSRegularExpression(pattern: #"\{\{\s*([^{}]+?)\s*\}\}"#)

    static func storageSyntax(for reference: String) -> String {
        let normalized = reference
            .replacingOccurrences(of: #"^\$nodes\."#, with: "steps.", options: .regularExpression)
            .replacingOccurrences(of: ".output.", with: ".")
        return "{{\(normalized)}}"
    }

    static func parse(_ template: String, outputs: [WorkflowMessageOutput]) -> [WorkflowMessageSegment] {
        let range = NSRange(template.startIndex..<template.endIndex, in: template)
        var segments: [WorkflowMessageSegment] = []
        var cursor = template.startIndex
        for match in pattern.matches(in: template, range: range) {
            guard let fullRange = Range(match.range, in: template),
                  let expressionRange = Range(match.range(at: 1), in: template) else { continue }
            if cursor < fullRange.lowerBound { segments.append(.text(String(template[cursor..<fullRange.lowerBound]))) }
            let expression = template[expressionRange].trimmingCharacters(in: .whitespacesAndNewlines)
            let reference = expression.replacingOccurrences(
                of: #"^steps\.([^.]+)\."#, with: "$nodes.$1.output.", options: .regularExpression
            )
            if let output = outputs.first(where: { $0.reference == reference }) {
                segments.append(.output(
                    reference: reference, label: output.label,
                    syntax: storageSyntax(for: reference), appId: output.appId
                ))
            } else {
                segments.append(.output(
                    reference: reference, label: fallbackLabel(for: reference),
                    syntax: "{{\(expression)}}", appId: nil
                ))
            }
            cursor = fullRange.upperBound
        }
        if cursor < template.endIndex { segments.append(.text(String(template[cursor...]))) }
        if segments.isEmpty { segments.append(.text(template)) }
        return segments
    }

    static func serialize(_ segments: [WorkflowMessageSegment]) -> String {
        segments.map(\.storageText).joined()
    }

    private static func fallbackLabel(for reference: String) -> String {
        if reference == "clock.now" { return AppStrings.workflowBuilder(.date_time) }
        if reference.hasPrefix("trigger.") { return friendly(String(reference.dropFirst("trigger.".count))) }
        let parts = reference.components(separatedBy: ".")
        if parts.count >= 4, parts[0] == "$nodes", parts[2] == "output" {
            return "\(friendly(parts[1])) · \(friendly(parts.dropFirst(3).joined(separator: ".")))"
        }
        return AppStrings.workflowBuilder(.select_output)
    }

    private static func friendly(_ value: String) -> String {
        value.replacingOccurrences(of: "[._]", with: " ", options: .regularExpression)
            .split(separator: " ")
            .map { $0.prefix(1).uppercased() + $0.dropFirst() }
            .joined(separator: " ")
    }
}
