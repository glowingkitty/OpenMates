// Sketch drawing tool — freehand drawing canvas for creating quick sketches to share.
// Mirrors the web app's enter_message/SketchView.svelte.
// Uses PencilKit on iOS/iPadOS for native Apple Pencil support.

import SwiftUI

#if os(iOS)
import PencilKit

struct SketchView: View {
    let onSave: (Data, String) -> Void
    let onCancel: () -> Void
    @State private var canvasView = PKCanvasView()
    @State private var selectedColor: UIColor = .label
    @State private var selectedWidth: CGFloat = 3
    @State private var toolType: PKInkingTool.InkType = .pen

    private let colors: [UIColor] = [.label, .systemRed, .systemBlue, .systemGreen, .systemOrange, .systemPurple]
    private let widths: [CGFloat] = [1, 3, 5, 8]

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                toolBar
                Divider()
                CanvasRepresentable(
                    canvasView: $canvasView,
                    toolType: toolType,
                    color: selectedColor,
                    width: selectedWidth
                )
            }
            .navigationTitle("Sketch")
            #if os(iOS)
            .navigationBarTitleDisplayMode(.inline)
            #endif
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { onCancel() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Send") { saveAndSend() }
                }
            }
        }
    }

    private var toolBar: some View {
        HStack(spacing: .spacing4) {
            // Tool type picker
            Picker("Tool", selection: $toolType) {
                Icon("modify", size: 18).tag(PKInkingTool.InkType.pen)
                Icon("modify", size: 18).tag(PKInkingTool.InkType.marker)
                Icon("design", size: 18).tag(PKInkingTool.InkType.pencil)
            }
            .pickerStyle(.segmented)
            .frame(width: 140)

            Divider().frame(height: 24)

            // Color picker
            ForEach(colors, id: \.self) { color in
                Circle()
                    .fill(Color(uiColor: color))
                    .frame(width: 24, height: 24)
                    .overlay {
                        if selectedColor == color {
                            Circle().stroke(.white, lineWidth: 2)
                                .frame(width: 20, height: 20)
                        }
                    }
                    .onTapGesture { selectedColor = color }
            }

            Divider().frame(height: 24)

            // Width picker
            ForEach(widths, id: \.self) { width in
                Circle()
                    .fill(Color.primary)
                    .frame(width: width + 8, height: width + 8)
                    .opacity(selectedWidth == width ? 1 : 0.3)
                    .onTapGesture { selectedWidth = width }
            }

            Spacer()

            // Undo / Clear
            Button { canvasView.undoManager?.undo() } label: {
                Icon("restore", size: 20)
            }
            Button { canvasView.drawing = PKDrawing() } label: {
                Icon("delete", size: 20)
            }
        }
        .padding(.horizontal, .spacing4)
        .padding(.vertical, .spacing2)
    }

    private func saveAndSend() {
        let drawing = canvasView.drawing
        let bounds = drawing.bounds
        guard !bounds.isEmpty else {
            onCancel()
            return
        }

        let image = drawing.image(from: bounds.insetBy(dx: -20, dy: -20), scale: UIScreen.main.scale)
        if let data = image.pngData() {
            let filename = "sketch-\(ISO8601DateFormatter().string(from: Date())).png"
            onSave(data, filename)
        }
    }
}

struct CanvasRepresentable: UIViewRepresentable {
    @Binding var canvasView: PKCanvasView
    let toolType: PKInkingTool.InkType
    let color: UIColor
    let width: CGFloat

    func makeUIView(context: Context) -> PKCanvasView {
        canvasView.drawingPolicy = .anyInput
        canvasView.backgroundColor = .systemBackground
        canvasView.tool = PKInkingTool(toolType, color: color, width: width)
        return canvasView
    }

    func updateUIView(_ uiView: PKCanvasView, context: Context) {
        uiView.tool = PKInkingTool(toolType, color: color, width: width)
    }
}
#endif
