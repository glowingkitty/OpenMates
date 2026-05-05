// Photo and file attachment picker for chat input.
// Supports camera, photo library, and document picker.
// Uploads via the upload server endpoint.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/packages/ui/src/components/enter_message/MessageInput.svelte
//         frontend/packages/ui/src/components/enter_message/ActionButtons.svelte
// CSS:    frontend/packages/ui/src/components/enter_message/MessageInput.styles.css
// Native counterpart of the custom attachment/action menu area.
// ────────────────────────────────────────────────────────────────────

import SwiftUI
import PhotosUI
#if os(iOS)
import UniformTypeIdentifiers
#endif

struct AttachmentPicker: View {
    @Binding var isPresented: Bool
    let onImageSelected: (Data, String) -> Void
    let onFileSelected: (URL) -> Void

    @State private var selectedPhotoItem: PhotosPickerItem?
    @State private var showDocumentPicker = false

    var body: some View {
        #if os(iOS)
        ZStack(alignment: .bottomLeading) {
            Button {
                withAnimation(.easeInOut(duration: 0.16)) {
                    isPresented.toggle()
                }
            } label: {
                Icon("files", size: 25)
                    .foregroundStyle(LinearGradient.primary)
                    .frame(width: 25, height: 25)
            }
            .buttonStyle(.plain)

            if isPresented {
                VStack(alignment: .leading, spacing: .spacing2) {
                    PhotosPicker(selection: $selectedPhotoItem, matching: .images) {
                        AttachmentMenuRow(icon: "image", title: "Photo Library")
                    }

                    Button {
                        isPresented = false
                        showDocumentPicker = true
                    } label: {
                        AttachmentMenuRow(icon: "files", title: "Browse Files")
                    }
                    .buttonStyle(.plain)
                }
                .padding(.spacing2)
                .background(Color.grey0)
                .clipShape(RoundedRectangle(cornerRadius: .radius7))
                .overlay(
                    RoundedRectangle(cornerRadius: .radius7)
                        .stroke(Color.grey20, lineWidth: 1)
                )
                .shadow(color: .black.opacity(0.16), radius: 12, x: 0, y: 6)
                .offset(y: -44)
                .zIndex(10)
            }
        }
        .onChange(of: selectedPhotoItem) { _, newValue in
            if let item = newValue {
                isPresented = false
                loadPhoto(item)
            }
        }
        .sheet(isPresented: $showDocumentPicker) {
            DocumentPickerView(onFileSelected: onFileSelected)
        }
        #else
        Button {
            openFilePicker()
        } label: {
            Icon("files", size: 25)
                .foregroundStyle(LinearGradient.primary)
        }
        .buttonStyle(.plain)
        #endif
    }

    private func loadPhoto(_ item: PhotosPickerItem) {
        Task {
            guard let data = try? await item.loadTransferable(type: Data.self) else { return }
            let filename = "photo_\(Int(Date().timeIntervalSince1970)).jpg"
            onImageSelected(data, filename)
            selectedPhotoItem = nil
        }
    }

    #if os(macOS)
    private func openFilePicker() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false
        if panel.runModal() == .OK, let url = panel.url {
            onFileSelected(url)
        }
    }
    #endif
}

private struct AttachmentMenuRow: View {
    let icon: String
    let title: String

    var body: some View {
        HStack(spacing: .spacing3) {
            Icon(icon, size: 17)
                .foregroundStyle(Color.fontSecondary)
            Text(title)
                .font(.omSmall)
                .foregroundStyle(Color.fontPrimary)
        }
        .padding(.horizontal, .spacing4)
        .padding(.vertical, .spacing3)
        .frame(minWidth: 164, alignment: .leading)
        .contentShape(Rectangle())
    }
}

#if os(iOS)
struct DocumentPickerView: UIViewControllerRepresentable {
    let onFileSelected: (URL) -> Void

    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: [
            .pdf, .plainText, .image, .audio, .spreadsheet, .presentation
        ])
        picker.allowsMultipleSelection = false
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ uiViewController: UIDocumentPickerViewController, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator(onFileSelected: onFileSelected)
    }

    class Coordinator: NSObject, UIDocumentPickerDelegate {
        let onFileSelected: (URL) -> Void

        init(onFileSelected: @escaping (URL) -> Void) {
            self.onFileSelected = onFileSelected
        }

        func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
            guard let url = urls.first else { return }
            if url.startAccessingSecurityScopedResource() {
                onFileSelected(url)
                url.stopAccessingSecurityScopedResource()
            }
        }
    }
}
#endif
