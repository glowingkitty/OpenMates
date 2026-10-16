// Web source: frontend/packages/ui/src/components/embeds/shared/EmbedVersionTimeline.svelte
// Rendered preview inspected at /dev/preview/embeds/shared/EmbedVersionTimeline?chrome=0.
// The unauthenticated error state was available; populated state requires the isolated fixture.
// Specification: specifications/architecture/storage-lifecycle/specification.yml
// Assertions: storage.versions.metadata-and-payload, storage.versions.bounded-reconstruction,
//             storage.surface.semantic-parity
import SwiftUI

struct EmbedVersionHistoryTimeline: View {
    @ObservedObject var history: EmbedVersionHistoryController
    var reopen: (() async -> Void)? = nil
    var body: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            HStack {
                Text(Self.text("title")).font(.omSmall.weight(.semibold))
                Spacer()
                Text(Self.text("loaded", ["count": String(history.versions.count)])).font(.omXs).foregroundStyle(Color.fontSecondary)
            }
            if history.loadingMetadata { ProgressView().accessibilityIdentifier("embed-version-timeline-loading") }
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: .spacing3) {
                    // Only authoritative metadata rows appear; unloaded versions are never invented.
                    ForEach(history.versions) { version in
                        Button { Task { await history.select(version.versionNumber) } } label: {
                            VStack(spacing: .spacing2) {
                                Circle().fill(version.versionNumber == history.selectedVersion ? Color.buttonPrimary : Color.grey30)
                                    .frame(width: 10, height: 10)
                                Text("v\(version.versionNumber)").font(.omMicro)
                            }.padding(.horizontal, .spacing4).padding(.vertical, .spacing3)
                        }
                        .buttonStyle(.plain).foregroundStyle(Color.fontPrimary)
                        .disabled(history.loadingMetadata)
                        .accessibilityIdentifier("embed-version-dot-\(version.versionNumber)")
                    }
                }
            }
            if history.isHistorical {
                Button { Task { await history.select(history.currentVersion) } } label: {
                    Text(Self.text("current", ["version": String(history.currentVersion)])).font(.omSmall)
                }.buttonStyle(.plain).foregroundStyle(Color.buttonPrimary)
                    .accessibilityIdentifier("embed-version-current")
            }
            if history.nextCursor != nil {
                Button { Task { await history.loadMore() } } label: { Text(Self.text("more")).font(.omSmall) }
                    .buttonStyle(.plain).foregroundStyle(Color.buttonPrimary)
                    .disabled(history.loadingMetadata || history.loadingContent)
                    .accessibilityIdentifier("embed-version-load-more")
            }
            Text(Self.text(history.isHistorical ? "historical" : "current", ["version": String(history.selectedVersion)]))
                .font(.omXs).foregroundStyle(Color.fontSecondary)
            if let selected = history.versions.first(where: { $0.versionNumber == history.selectedVersion }), selected.createdAt > 0 {
                Text(Date(timeIntervalSince1970: TimeInterval(selected.createdAt)), style: .date)
                    .font(.omXs).foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("embed-version-edit-time")
            }
            if history.loadingContent { ProgressView().accessibilityIdentifier("embed-version-content-loading") }
            if let failure = history.failure {
                Text(Self.failureText(failure)).font(.omSmall).foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("embed-version-history-error")
                Button { Task {
                    if history.failure == .accessChanged || history.versions.isEmpty, let reopen { await reopen() }
                    else { await history.retry() }
                } } label: { Text(Self.text("common.retry", absolute: true)).font(.omSmall) }
                    .buttonStyle(.plain).foregroundStyle(Color.buttonPrimary)
                    .accessibilityIdentifier("embed-version-history-retry")
            } else if history.versions.isEmpty && !history.loadingMetadata {
                Text(Self.text("empty")).font(.omSmall).foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("embed-version-timeline-empty")
            }
            // History consumption never promises an unimplemented restore mutation.
            Text(Self.text("readonly")).font(.omXs).foregroundStyle(Color.fontSecondary)
                .accessibilityIdentifier("embed-version-readonly")
        }
        .padding(.spacing5).foregroundStyle(Color.fontPrimary).background(Color.grey10)
        .clipShape(RoundedRectangle(cornerRadius: .radius5))
        .accessibilityIdentifier("embed-version-timeline")
    }
    static func text(_ key: String, _ replacements: [String: String] = [:], absolute: Bool = false) -> String {
        let fullKey = absolute ? key : "artifact_history." + key
        #if os(watchOS)
        return WatchLocalization.text(fullKey, replacements: replacements)
        #else
        return LocalizationManager.shared.text(fullKey, replacements: replacements)
        #endif
    }
    static func failureText(_ failure: EmbedVersionHistoryFailure) -> String {
        switch failure {
        case .snapshotRequired: return Self.text("snapshot_required")
        case .accessChanged: return Self.text("access_changed")
        case .payloadTooLarge: return Self.text("too_large")
        case .invalidResponse, .unavailable: return Self.text("failed")
        }
    }
}

/// A selected version replaces cached content only after exact authenticated
/// reconstruction. Pending/failed selections never relabel the cached payload.
struct EmbedHistoricalVersionContent: View {
    @ObservedObject var history: EmbedVersionHistoryController
    var body: some View {
        Group {
            if let content = history.content {
                ScrollView(.horizontal) {
                    Text(content).font(.omSmall.monospaced()).foregroundStyle(Color.fontPrimary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        #if !os(watchOS)
                        .textSelection(.enabled)
                        #endif
                }.accessibilityIdentifier("embed-historical-version-content")
            } else if history.loadingContent {
                ProgressView().accessibilityIdentifier("embed-version-content-loading")
            } else {
                Text(history.failure.map(EmbedVersionHistoryTimeline.failureText) ?? EmbedVersionHistoryTimeline.text("select"))
                    .font(.omSmall).foregroundStyle(Color.fontSecondary)
                    .accessibilityIdentifier("embed-historical-version-unavailable")
            }
        }
    }
}
