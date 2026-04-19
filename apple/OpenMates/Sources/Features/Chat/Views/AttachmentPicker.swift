// Photo and file attachment picker for chat input.
// Supports camera, photo library, and document picker.
// Uploads via the upload server endpoint.

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
        Menu {
            PhotosPicker(selection: $selectedPhotoItem, matching: .images) {
                Label("Photo Library", systemImage: "photo.on.rectangle")
            }

            Button {
                showDocumentPicker = true
            } label: {
                Label("Browse Files", systemImage: "folder")
            }
        } label: {
            Icon("plus", size: 24)
                .foregroundStyle(Color.fontTertiary)
        }
        .onChange(of: selectedPhotoItem) { _, newValue in
            if let item = newValue {
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
            Icon("files", size: 18)
                .foregroundStyle(Color.fontTertiary)
        }
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
