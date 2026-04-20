// Camera capture — take a photo directly from the chat input to attach to a message.
// Mirrors the web app's enter_message/CameraView.svelte.
// Uses UIImagePickerController wrapped in UIViewControllerRepresentable.

import SwiftUI

#if os(iOS)
struct CameraCaptureView: UIViewControllerRepresentable {
    let onCapture: (Data, String) -> Void
    let onCancel: () -> Void

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = .camera
        picker.cameraCaptureMode = .photo
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ uiViewController: UIImagePickerController, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator(onCapture: onCapture, onCancel: onCancel)
    }

    class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let onCapture: (Data, String) -> Void
        let onCancel: () -> Void

        init(onCapture: @escaping (Data, String) -> Void, onCancel: @escaping () -> Void) {
            self.onCapture = onCapture
            self.onCancel = onCancel
        }

        func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            if let image = info[.originalImage] as? UIImage,
               let data = image.jpegData(compressionQuality: 0.85) {
                let filename = "photo-\(ISO8601DateFormatter().string(from: Date())).jpg"
                onCapture(data, filename)
            }
            picker.dismiss(animated: true)
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
            onCancel()
            picker.dismiss(animated: true)
        }
    }
}
#endif

struct CameraButton: View {
    let onCapture: (Data, String) -> Void
    @State private var showCamera = false

    var body: some View {
        Button {
            showCamera = true
        } label: {
            Icon("camera", size: 20)
                .foregroundStyle(Color.fontSecondary)
        }
        .accessibilityLabel("Take photo")
        .accessibilityHint("Opens camera to capture a photo for this chat")
        #if os(iOS)
        .fullScreenCover(isPresented: $showCamera) {
            CameraCaptureView(
                onCapture: { data, filename in
                    showCamera = false
                    onCapture(data, filename)
                },
                onCancel: { showCamera = false }
            )
            .ignoresSafeArea()
        }
        #endif
    }
}
