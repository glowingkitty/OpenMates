// In-app issue reporting for the Apple app.
// Mirrors the web SettingsReportIssue.svelte flow and the shared
// /v1/settings/issues backend contract without using stock product UI chrome.
// The form collects safe context only: no message plaintext, keys, credentials,
// private paths, hostnames, or share fragments are included automatically.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/settings/SettingsReportIssue.svelte
// TS:      frontend/packages/ui/src/services/issueReportSubmission.ts
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import Foundation
import PhotosUI
import SwiftUI
#if os(iOS)
import UIKit
#elseif os(macOS)
import AppKit
#endif

struct ReportIssuePrefill: Equatable {
    let id = UUID()
    let title: String
    let category: String

    @MainActor static func assistantResponseQuality() -> ReportIssuePrefill {
        ReportIssuePrefill(title: AppStrings.assistantFeedbackReportTitle, category: "bug")
    }

    @MainActor static func featureRequest() -> ReportIssuePrefill {
        ReportIssuePrefill(title: AppStrings.requestFeaturePrefill, category: "feature")
    }
}

struct ReportIssueView: View {
    @State private var title = ""
    @State private var userFlow = ""
    @State private var expectedBehaviour = ""
    @State private var actualBehaviour = ""
    @State private var issueType: IssueReportPayloadBuilder.IssueType = .bugReport
    @State private var screenshotItem: PhotosPickerItem?
    @State private var screenshotData: Data?
    @State private var screenshotPreview: Image?
    @State private var isSubmitting = false
    @State private var submittedIssueReference: String?
    @State private var error: String?
    @State private var uiTestIssueLogPayloadText: String?

    private var titleValidationError: String? {
        let trimmedTitle = title.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmedTitle.isEmpty { return AppStrings.reportIssueTitleRequired }
        if trimmedTitle.count < 3 { return AppStrings.reportIssueTitleTooShort }
        return nil
    }

    private var isValid: Bool {
        titleValidationError == nil
    }

    init(prefill: ReportIssuePrefill? = nil) {
        _title = State(initialValue: prefill?.title ?? "")
        _issueType = State(initialValue: prefill?.category == "feature" ? .featureRequest : .bugReport)
    }

    var body: some View {
        OMSettingsPage(title: AppStrings.settingsReportIssue, subtitle: AppStrings.reportIssueDescription, showsHeader: false) {
            Color.clear
                .frame(height: 0)
                .accessibilityIdentifier("settings-report-issue-form")

            if let submittedIssueReference {
                submittedView(reference: submittedIssueReference)
            } else {
                formView
            }

            #if DEBUG
            if ProcessInfo.processInfo.arguments.contains("--ui-test-report-issue-success"),
               let uiTestIssueLogPayloadText {
                Text(uiTestIssueLogPayloadText)
                    .font(.omMicro)
                    .foregroundStyle(Color.fontTertiary)
                    .accessibilityIdentifier("report-issue-debug-log-payload")
            }
            #endif
        }
        .onAppear {
            seedUITestReportIssueLogsIfNeeded()
        }
        .onChange(of: screenshotItem) { _, newItem in
            loadScreenshot(newItem)
        }
    }

    private var formView: some View {
        VStack(alignment: .leading, spacing: .spacing8) {
            OMSettingsSection(AppStrings.settingsReportIssue, icon: "report_issue") {
                VStack(alignment: .leading, spacing: .spacing5) {
                    ReportIssueTextArea(
                        title: AppStrings.reportIssueTitleLabel,
                        placeholder: AppStrings.reportIssueTitlePlaceholder,
                        text: $title,
                        minHeight: 92,
                        accessibilityIdentifier: "report-issue-title"
                    )

                    if let titleValidationError {
                        Text(titleValidationError)
                            .font(.omXs)
                            .foregroundStyle(Color.error)
                            .accessibilityIdentifier("report-issue-title-error")
                    }

                    ReportIssueTextArea(
                        title: AppStrings.reportIssueUserFlowLabel,
                        placeholder: AppStrings.reportIssueUserFlowPlaceholder,
                        hint: AppStrings.reportIssueUserFlowHint,
                        text: $userFlow,
                        accessibilityIdentifier: "report-issue-user-flow"
                    )

                    ReportIssueTextArea(
                        title: AppStrings.reportIssueExpectedLabel,
                        placeholder: AppStrings.reportIssueExpectedPlaceholder,
                        hint: AppStrings.reportIssueExpectedHint,
                        text: $expectedBehaviour,
                        accessibilityIdentifier: "report-issue-expected"
                    )

                    ReportIssueTextArea(
                        title: AppStrings.reportIssueActualLabel,
                        placeholder: AppStrings.reportIssueActualPlaceholder,
                        hint: AppStrings.reportIssueActualHint,
                        text: $actualBehaviour,
                        accessibilityIdentifier: "report-issue-actual"
                    )
                }
                .padding(.horizontal, .spacing5)
                .padding(.vertical, .spacing4)
            }

            screenshotSection

            if let error {
                Text(error)
                    .font(.omSmall)
                    .foregroundStyle(Color.error)
                    .padding(.horizontal, .spacing5)
                    .accessibilityIdentifier("report-issue-error")
            }

            Button {
                submitReport()
            } label: {
                if isSubmitting {
                    ProgressView()
                        .accessibilityLabel(AppStrings.reportIssueSubmitting)
                } else {
                    Text(AppStrings.reportIssueSubmitButton)
                }
            }
            .buttonStyle(OMPrimaryButtonStyle())
            .disabled(!isValid || isSubmitting)
            .accessibilityIdentifier("report-issue-submit")
        }
    }

    private var screenshotSection: some View {
        OMSettingsSection(AppStrings.reportIssueScreenshotLabel, icon: "image") {
            VStack(alignment: .leading, spacing: .spacing4) {
                Text(AppStrings.reportIssueScreenshotHint)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)

                if let screenshotPreview {
                    screenshotPreview
                        .resizable()
                        .scaledToFit()
                        .frame(maxHeight: 200)
                        .clipShape(RoundedRectangle(cornerRadius: .radius5))
                        .accessibilityIdentifier("report-issue-screenshot-preview")

                    Button {
                        screenshotData = nil
                        self.screenshotPreview = nil
                        screenshotItem = nil
                    } label: {
                        Label {
                            Text(AppStrings.reportIssueScreenshotRemove)
                        } icon: {
                            Icon("close", size: 16)
                        }
                    }
                    .buttonStyle(OMSecondaryButtonStyle())
                    .accessibilityIdentifier("report-issue-remove-screenshot")
                } else {
                    PhotosPicker(selection: $screenshotItem, matching: .images) {
                        HStack(spacing: .spacing3) {
                            Icon("image", size: 18)
                            Text(AppStrings.reportIssueScreenshotUploadButton)
                        }
                    }
                    .buttonStyle(OMSecondaryButtonStyle())
                    .accessibilityIdentifier("report-issue-attach-screenshot")
                }
            }
            .padding(.horizontal, .spacing5)
            .padding(.vertical, .spacing4)
        }
    }

    private func submittedView(reference: String) -> some View {
        OMSettingsSection(AppStrings.reportIssueSuccess, icon: "check") {
            VStack(alignment: .center, spacing: .spacing5) {
                ZStack {
                    Circle()
                        .fill(LinearGradient.primary)
                        .frame(width: 64, height: 64)
                    Icon("check", size: 34)
                        .foregroundStyle(Color.white)
                }
                .accessibilityHidden(true)

                Text(AppStrings.reportIssueSuccess)
                    .font(.omH3)
                    .fontWeight(.semibold)
                    .foregroundStyle(Color.fontPrimary)
                    .multilineTextAlignment(.center)

                Text("\(AppStrings.reportIssueIssueIdLabel): \(reference)")
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                    .textSelection(.enabled)
                    .accessibilityIdentifier("report-issue-reference")
            }
            .frame(maxWidth: .infinity)
            .padding(.horizontal, .spacing5)
            .padding(.vertical, .spacing8)
        }
        .onAppear {
            AccessibilityAnnouncement.announce(AppStrings.reportIssueSuccess)
        }
    }

    private func loadScreenshot(_ item: PhotosPickerItem?) {
        guard let item else { return }
        Task {
            if let data = try? await item.loadTransferable(type: Data.self) {
                screenshotData = data
                #if os(iOS)
                if let uiImage = UIImage(data: data) {
                    screenshotPreview = Image(uiImage: uiImage)
                }
                #elseif os(macOS)
                if let nsImage = NSImage(data: data) {
                    screenshotPreview = Image(nsImage: nsImage)
                }
                #endif
            }
        }
    }

    private func submitReport() {
        guard isValid else { return }
        isSubmitting = true
        error = nil
        NativeClientLogCollector.shared.record(level: .info, category: "report_issue", message: "Submitting native issue report")

        Task {
            do {
                let payload = IssueReportPayloadBuilder.makePayload(
                    title: title,
                    issueType: issueType,
                    userFlow: userFlow,
                    expectedBehaviour: expectedBehaviour,
                    actualBehaviour: actualBehaviour,
                    screenshotData: screenshotData,
                    consoleLogs: NativeClientLogCollector.shared.logsAsText(limit: 100),
                    runtimeDebugState: IssueReportPayloadBuilder.runtimeDebugState()
                )
                let payloadData = try JSONSerialization.data(withJSONObject: payload)

                let response: IssueReportResponse = try await APIClient.shared.request(
                    .post,
                    path: "/v1/settings/issues",
                    body: JSONRawBody(data: payloadData)
                )

                let reference = response.shortIssueId ?? response.issueId ?? ""
                if let issueId = response.issueId {
                    await sendIssueLogs(issueId: issueId)
                }
                submittedIssueReference = reference.isEmpty ? AppStrings.done : reference
                NativeClientLogCollector.shared.record(level: .info, category: "report_issue", message: "Native issue report submitted")
            } catch {
                NativeClientLogCollector.shared.record(level: .error, category: "report_issue", message: error.localizedDescription)
                self.error = error.localizedDescription
                AccessibilityAnnouncement.announce(error.localizedDescription)
            }
            isSubmitting = false
        }
    }

    private func sendIssueLogs(issueId: String) async {
        let payload = NativeClientLogCollector.shared.issueLogPayload(
            issueId: issueId,
            pageURL: "apple://settings/report_issue"
        )
        #if DEBUG
        uiTestIssueLogPayloadText = Self.uiTestIssueLogDebugText(payload)
        #endif
        let payloadData: Data
        do {
            payloadData = try JSONSerialization.data(withJSONObject: payload)
        } catch {
            NativeClientLogCollector.shared.record(level: .error, category: "report_issue", message: "Issue log serialization failed: \(error.localizedDescription)")
            return
        }

        do {
            let _: Data = try await APIClient.shared.request(
                .post,
                path: "/v1/settings/issue-logs",
                body: JSONRawBody(data: payloadData)
            )
        } catch {
            NativeClientLogCollector.shared.record(level: .warning, category: "report_issue", message: "Issue log upload failed: \(error.localizedDescription)")
        }
    }

    #if DEBUG
    private func seedUITestReportIssueLogsIfNeeded() {
        guard ProcessInfo.processInfo.arguments.contains("--ui-test-seed-report-logs") else { return }
        let environment = ProcessInfo.processInfo.environment
        let simulatorName = environment["SIMULATOR_DEVICE_NAME"] ?? "unknown-simulator"
        let simulatorModel = environment["SIMULATOR_MODEL_IDENTIFIER"] ?? "unknown-model"
        NativeClientLogCollector.shared.record(
            level: .warning,
            category: "ui_test_simulator",
            message: "Report issue simulator diagnostic from \(simulatorName) \(simulatorModel) for tester@example.org token=secret"
        )
    }

    private static func uiTestIssueLogDebugText(_ payload: [String: Any]) -> String {
        [
            "issue_id=\(payload["issue_id"] as? String ?? "")",
            "page_url=\(payload["page_url"] as? String ?? "")",
            "user_agent=\(payload["user_agent"] as? String ?? "")",
            "logs_text=\(payload["logs_text"] as? String ?? "")",
        ].joined(separator: "\n")
    }
    #endif
}

private struct ReportIssueTextArea: View {
    let title: String
    let placeholder: String
    var hint: String?
    @Binding var text: String
    var minHeight: CGFloat = 120
    let accessibilityIdentifier: String

    var body: some View {
        VStack(alignment: .leading, spacing: .spacing2) {
            Text(title)
                .font(.omSmall.weight(.semibold))
                .foregroundStyle(Color.fontPrimary)

            ZStack(alignment: .topLeading) {
                TextEditor(text: $text)
                    .font(.omP)
                    .foregroundStyle(Color.fontPrimary)
                    .scrollContentBackground(.hidden)
                    .padding(.horizontal, .spacing5)
                    .padding(.vertical, .spacing4)
                    .frame(minHeight: minHeight)
                    .background(Color.grey0)
                    .clipShape(RoundedRectangle(cornerRadius: .radius5))
                    .overlay(
                        RoundedRectangle(cornerRadius: .radius5)
                            .stroke(Color.grey30, lineWidth: 1)
                    )
                    .accessibilityIdentifier(accessibilityIdentifier)

                if text.isEmpty {
                    Text(placeholder)
                        .font(.omP)
                        .foregroundStyle(Color.fontTertiary)
                        .padding(.horizontal, .spacing8)
                        .padding(.vertical, .spacing6)
                        .allowsHitTesting(false)
                        .accessibilityHidden(true)
                }
            }

            if let hint {
                Text(hint)
                    .font(.omXs)
                    .foregroundStyle(Color.fontSecondary)
            }
        }
    }
}

struct IssueReportResponse: Decodable {
    let success: Bool
    let message: String
    let issueId: String?
    let shortIssueId: String?
    let screenshotUploaded: Bool
}

enum IssueReportPayloadBuilder {
    enum IssueType: String {
        case bugReport = "bug_report"
        case featureRequest = "feature_request"
    }

    static func makePayload(
        title: String,
        issueType: IssueType,
        userFlow: String,
        expectedBehaviour: String,
        actualBehaviour: String,
        screenshotData: Data?,
        consoleLogs: String,
        runtimeDebugState: [String: Any],
        language: String = Locale.current.language.languageCode?.identifier ?? "en"
    ) -> [String: Any] {
        var payload: [String: Any] = [
            "title": sanitizedText(title),
            "issue_type": issueType.rawValue,
            "language": language,
            "device_info": deviceInfo(),
            "console_logs": NativeClientLogCollector.sanitize(consoleLogs),
            "runtime_debug_state": runtimeDebugState,
            "action_history": "native:settings/report_issue",
            "trace_ids": [],
            "add_to_linear": true,
            "send_email_notification": true,
        ]

        let description = composedDescription(
            userFlow: userFlow,
            expectedBehaviour: expectedBehaviour,
            actualBehaviour: actualBehaviour
        )
        if !description.isEmpty {
            payload["description"] = description
        }

        if let screenshotData {
            payload["screenshot_png_base64"] = screenshotData.base64EncodedString()
        }

        return payload
    }

    static func composedDescription(userFlow: String, expectedBehaviour: String, actualBehaviour: String) -> String {
        [
            ("What did you do?", userFlow),
            ("Expected behaviour", expectedBehaviour),
            ("Actual behaviour", actualBehaviour),
        ]
        .compactMap { heading, value in
            let clean = sanitizedText(value)
            return clean.isEmpty ? nil : "## \(heading)\n\(clean)"
        }
        .joined(separator: "\n\n")
    }

    static func runtimeDebugState() -> [String: Any] {
        [
            "platform": "apple_native",
            "bundle_id": Bundle.main.bundleIdentifier ?? "org.openmates.app",
            "app_version": Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "unknown",
        ]
    }

    static func deviceInfo() -> [String: Any] {
        #if os(iOS)
        let environment = ProcessInfo.processInfo.environment
        var info: [String: Any] = [
            "userAgent": "OpenMates-Apple/iOS",
            "viewportWidth": 0,
            "viewportHeight": 0,
            "isTouchEnabled": true,
            "systemVersion": ProcessInfo.processInfo.operatingSystemVersionString,
        ]
        if let simulatorName = environment["SIMULATOR_DEVICE_NAME"] {
            info["simulatorDeviceName"] = NativeClientLogCollector.sanitize(simulatorName)
        }
        if let simulatorModel = environment["SIMULATOR_MODEL_IDENTIFIER"] {
            info["simulatorModelIdentifier"] = NativeClientLogCollector.sanitize(simulatorModel)
        }
        if let simulatorRuntime = environment["SIMULATOR_RUNTIME_VERSION"] {
            info["simulatorRuntimeVersion"] = NativeClientLogCollector.sanitize(simulatorRuntime)
        }
        info["isSimulator"] = environment["SIMULATOR_DEVICE_NAME"] != nil
        return info
        #elseif os(macOS)
        let frame = NSScreen.main?.frame ?? .zero
        return [
            "userAgent": "OpenMates-Apple/macOS",
            "viewportWidth": Int(frame.width),
            "viewportHeight": Int(frame.height),
            "isTouchEnabled": false,
            "systemVersion": ProcessInfo.processInfo.operatingSystemVersionString,
        ]
        #else
        return ["userAgent": "OpenMates-Apple", "isTouchEnabled": false]
        #endif
    }

    static func sanitizedText(_ value: String) -> String {
        NativeClientLogCollector.sanitize(value)
            .replacingOccurrences(of: "<[^>]*>", with: "", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

enum NativeClientLogLevel: String {
    case debug
    case info
    case warning
    case error
}

struct NativeClientLogEntry: Equatable {
    let timestamp: Date
    let level: NativeClientLogLevel
    let category: String
    let message: String
}

final class NativeClientLogCollector: @unchecked Sendable {
    static let shared = NativeClientLogCollector()
    private static let maxEntries = 200
    private let lock = NSLock()
    private var entries: [NativeClientLogEntry] = []

    private init() {}

    func record(level: NativeClientLogLevel, category: String, message: String) {
        let entry = NativeClientLogEntry(
            timestamp: Date(),
            level: level,
            category: Self.sanitize(category),
            message: Self.sanitize(message)
        )
        lock.lock()
        entries.append(entry)
        if entries.count > Self.maxEntries {
            entries.removeFirst(entries.count - Self.maxEntries)
        }
        lock.unlock()
    }

    func resetForTests() {
        lock.lock()
        entries.removeAll()
        lock.unlock()
    }

    func logsAsText(limit: Int) -> String {
        lock.lock()
        let snapshot = Array(entries.suffix(max(0, limit)))
        lock.unlock()

        let formatter = ISO8601DateFormatter()
        return snapshot.map { entry in
            "[\(formatter.string(from: entry.timestamp))] [\(entry.level.rawValue.uppercased())] [\(entry.category)] \(entry.message)"
        }.joined(separator: "\n")
    }

    func issueLogPayload(issueId: String, pageURL: String) -> [String: Any] {
        [
            "issue_id": issueId,
            "logs_text": logsAsText(limit: 150),
            "page_url": Self.sanitize(pageURL),
            "user_agent": "OpenMates-Apple",
        ]
    }

    static func sanitize(_ value: String) -> String {
        var sanitized = value
        let replacements: [(String, String)] = [
            (#"#[A-Za-z0-9_-]*key=[^\s\]]+"#, "#key=<redacted>"),
            (#"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}"#, "<email>"),
            (#"(?i)(password|token|secret|api[_-]?key)=([^\s&]+)"#, "$1=<redacted>"),
            (#"file://[^\s\]]+"#, "file://<redacted>"),
        ]
        for (pattern, replacement) in replacements {
            sanitized = sanitized.replacingOccurrences(
                of: pattern,
                with: replacement,
                options: [.regularExpression, .caseInsensitive]
            )
        }
        return sanitized
    }
}
