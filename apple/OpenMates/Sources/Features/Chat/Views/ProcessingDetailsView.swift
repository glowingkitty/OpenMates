// Processing details — shows what the AI is doing during request processing.
// Mirrors the web app's ProcessingDetails.svelte: "Using apps", "Loaded preferences",
// skill execution steps, and preprocessing progress.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/ProcessingDetails.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

struct ProcessingDetailsView: View {
    let steps: [ProcessingStep]
    let isComplete: Bool

    struct ProcessingStep: Identifiable {
        let id = UUID()
        let type: StepType
        let label: String
        let appId: String?
        let isComplete: Bool

        enum StepType {
            case loadingPreferences
            case usingApp
            case preprocessing
            case executingSkill
            case generatingResponse
        }
    }

    var body: some View {
        if !steps.isEmpty {
            VStack(alignment: .leading, spacing: .spacing2) {
                ForEach(steps) { step in
                    HStack(spacing: .spacing3) {
                        if step.isComplete {
                            Icon("check", size: 12)
                                .foregroundStyle(.green)
                        } else {
                            ProgressView()
                                .scaleEffect(0.6)
                                .frame(width: 12, height: 12)
                        }

                        if let appId = step.appId {
                            AppIconView(appId: appId, size: 16)
                        }

                        Text(step.label)
                            .font(.omXs)
                            .foregroundStyle(step.isComplete ? Color.fontTertiary : Color.fontSecondary)
                    }
                    .transition(.opacity.combined(with: .move(edge: .top)))
                }
            }
            .padding(.horizontal, .spacing4)
            .padding(.vertical, .spacing3)
            .background(Color.grey10.opacity(0.5))
            .clipShape(RoundedRectangle(cornerRadius: .radius3))
            .animation(.easeInOut(duration: 0.2), value: steps.count)
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Processing: \(steps.filter { !$0.isComplete }.first?.label ?? "complete")")
        }
    }
}

// MARK: - Convenience init from streaming preprocessing events

extension ProcessingDetailsView.ProcessingStep {
    static func fromPreprocessing(_ stepName: String) -> ProcessingDetailsView.ProcessingStep {
        let (label, appId) = parseStepName(stepName)
        return ProcessingDetailsView.ProcessingStep(
            type: .preprocessing,
            label: label,
            appId: appId,
            isComplete: false
        )
    }

    private static func parseStepName(_ name: String) -> (String, String?) {
        switch name {
        case "loading_preferences": return ("Loading preferences", nil)
        case "loading_memories": return ("Loading memories", nil)
        case "detecting_language": return ("Detecting language", nil)
        case "pii_detection": return ("Checking for personal data", nil)
        case "selecting_model": return ("Selecting AI model", nil)
        case _ where name.hasPrefix("skill_"):
            let skillName = String(name.dropFirst(6)).replacingOccurrences(of: "_", with: " ").capitalized
            return ("Running \(skillName)", nil)
        case _ where name.hasPrefix("app:"):
            let parts = name.split(separator: ":")
            let appId = parts.count > 1 ? String(parts[1]) : nil
            return ("Using \(appId?.capitalized ?? "app")", appId)
        default:
            return (name.replacingOccurrences(of: "_", with: " ").capitalized, nil)
        }
    }
}
