// Sketch drawing tool — freehand drawing canvas for creating quick sketches to share.
// Mirrors the web app's enter_message/SketchView.svelte.
// Uses PencilKit on iOS/iPadOS for native Apple Pencil support.

import SwiftUI

#if os(iOS)
import PencilKit

struct SketchComposerOverlay: View {
    let onSave: (Data, String) -> Void
    let onCancel: () -> Void
    @State private var canvasView = PKCanvasView()
    @State private var selectedColor: UIColor = .label
    @State private var selectedWidth: CGFloat = 3
    @State private var toolType: PKInkingTool.InkType = .pen

    private let colors: [UIColor] = [.label, .systemRed, .systemBlue, .systemGreen, .systemOrange, .systemPurple]
    private let widths: [CGFloat] = [1, 3, 5, 8]

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: .spacing4) {
                sketchToolButton(type: .pen, icon: "modify")
                sketchToolButton(type: .marker, icon: "design")
                sketchToolButton(type: .pencil, icon: "pencil")

                Divider().frame(height: 24)

                ForEach(colors, id: \.self) { color in
                    Circle()
                        .fill(Color(uiColor: color))
                        .frame(width: 24, height: 24)
                        .overlay {
                            if selectedColor == color {
                                Circle().stroke(Color.grey0, lineWidth: 2)
                                    .frame(width: 20, height: 20)
                            }
                        }
                        .onTapGesture { selectedColor = color }
                }

                Divider().frame(height: 24)

                ForEach(widths, id: \.self) { width in
                    Circle()
                        .fill(Color.fontPrimary)
                        .frame(width: width + 8, height: width + 8)
                        .opacity(selectedWidth == width ? 1 : 0.3)
                        .onTapGesture { selectedWidth = width }
                }

                Spacer()

                Button(action: onCancel) {
                    Icon("close", size: 20).foregroundStyle(Color.fontSecondary)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(AppStrings.cancel)

                Button(action: saveAndSend) {
                    Text(AppStrings.sendAction)
                        .font(.omSmall.weight(.medium))
                        .foregroundStyle(Color.fontButton)
                        .padding(.horizontal, .spacing8)
                        .frame(height: 40)
                        .background(Color.buttonPrimary)
                        .clipShape(RoundedRectangle(cornerRadius: .radius8))
                }
                .buttonStyle(.plain)
                .accessibilityLabel(AppStrings.sendAction)
            }
            .padding(.horizontal, .spacing5)
            .frame(height: 53)
            .background(Color.grey0.opacity(0.94))

            CanvasRepresentable(
                canvasView: $canvasView,
                toolType: toolType,
                color: selectedColor,
                width: selectedWidth
            )
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: 24))
        .clipped()
    }

    private func sketchToolButton(type: PKInkingTool.InkType, icon: String) -> some View {
        Button { toolType = type } label: {
            Icon(icon, size: 18)
                .foregroundStyle(toolType == type ? Color.fontButton : Color.fontSecondary)
                .frame(width: 32, height: 32)
                .background(toolType == type ? Color.buttonPrimary : Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius3))
        }
        .buttonStyle(.plain)
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

struct SketchView: View {
    let onSave: (Data, String) -> Void
    let onCancel: () -> Void

    var body: some View {
        SketchComposerOverlay(onSave: onSave, onCancel: onCancel)
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
