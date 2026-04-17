// In-app issue reporting — submit bug reports with title, description, and screenshots.
// Mirrors the web app's report-issue-flow: form validation, screenshot attachment,
// and submission to the backend issue tracker endpoint.

import SwiftUI
import PhotosUI

struct ReportIssueView: View {
    @Environment(\.dismiss) var dismiss
    @State private var title = ""
    @State private var description = ""
    @State private var category = "bug"
    @State private var screenshotItem: PhotosPickerItem?
    @State private var screenshotData: Data?
    @State private var screenshotPreview: Image?
    @State private var isSubmitting = false
    @State private var submitted = false
    @State private var error: String?

    private let categories = [
        ("bug", "Bug Report"),
        ("feature", "Feature Request"),
        ("account", "Account Issue"),
        ("billing", "Billing Issue"),
        ("other", "Other")
    ]

    private var isValid: Bool {
        !title.trimmingCharacters(in: .whitespaces).isEmpty &&
        !description.trimmingCharacters(in: .whitespaces).isEmpty
    }

    var body: some View {
        NavigationStack {
            if submitted {
                submittedView
            } else {
                formView
            }
        }
    }

    // MARK: - Form

    private var formView: some View {
        Form {
            Section("Category") {
                Picker("Category", selection: $category) {
                    ForEach(categories, id: \.0) { id, name in
                        Text(name).tag(id)
                    }
                }
                .pickerStyle(.menu)
            }

            Section("Details") {
                TextField("Title", text: $title)
                    .autocorrectionDisabled()

                TextEditor(text: $description)
                    .frame(minHeight: 120)
                    .font(.omP)
                    .overlay(alignment: .topLeading) {
                        if description.isEmpty {
                            Text("Describe the issue...")
                                .font(.omP)
                                .foregroundStyle(Color.fontTertiary)
                                .padding(.top, 8)
                                .padding(.leading, 4)
                                .allowsHitTesting(false)
                        }
                    }
            }

            Section("Screenshot (optional)") {
                if let screenshotPreview {
                    screenshotPreview
                        .resizable()
                        .scaledToFit()
                        .frame(maxHeight: 200)
                        .clipShape(RoundedRectangle(cornerRadius: .radius3))
                        .overlay(alignment: .topTrailing) {
                            Button {
                                self.screenshotData = nil
                                self.screenshotPreview = nil
                                self.screenshotItem = nil
                            } label: {
                                Image(systemName: "xmark.circle.fill")
                                    .foregroundStyle(.white, Color.error)
                            }
                            .padding(.spacing2)
                        }
                } else {
                    PhotosPicker(selection: $screenshotItem, matching: .screenshots) {
                        Label("Attach Screenshot", systemImage: "camera")
                    }
                }
            }

            if let error {
                Section {
                    Text(error)
                        .font(.omSmall)
                        .foregroundStyle(Color.error)
                }
            }

            Section {
                Button {
                    submitReport()
                } label: {
                    HStack {
                        Spacer()
                        if isSubmitting {
                            ProgressView()
                        } else {
                            Text("Submit Report")
                                .fontWeight(.medium)
                        }
                        Spacer()
                    }
                }
                .disabled(!isValid || isSubmitting)
            }
        }
        .navigationTitle("Report an Issue")
        #if os(iOS)
        .navigationBarTitleDisplayMode(.inline)
        #endif
        .toolbar {
            ToolbarItem(placement: .cancellationAction) {
                Button("Cancel") { dismiss() }
            }
        }
        .onChange(of: screenshotItem) { _, newItem in
            loadScreenshot(newItem)
        }
    }

    // MARK: - Submitted confirmation

    private var submittedView: some View {
        VStack(spacing: .spacing6) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 48))
                .foregroundStyle(.green)

            Text("Report Submitted")
                .font(.omH3).fontWeight(.semibold)

            Text("Thank you for helping us improve OpenMates.")
                .font(.omP)
                .foregroundStyle(Color.fontSecondary)
                .multilineTextAlignment(.center)

            Button("Done") { dismiss() }
                .buttonStyle(.borderedProminent)
                .tint(Color.buttonPrimary)
        }
        .padding(.spacing8)
        .navigationTitle("Report an Issue")
        #if os(iOS)
        .navigationBarTitleDisplayMode(.inline)
        #endif
    }

    // MARK: - Actions

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
        isSubmitting = true
        error = nil

        Task {
            do {
                var body: [String: Any] = [
                    "title": title,
                    "description": description,
                    "category": category,
                    "platform": "apple_native"
                ]

                if let screenshotData {
                    body["screenshot_base64"] = screenshotData.base64EncodedString()
                }

                let _: Data = try await APIClient.shared.request(
                    .post, path: "/v1/issues/report", body: body
                )
                submitted = true
            } catch {
                self.error = error.localizedDescription
            }
            isSubmitting = false
        }
    }
}
