// PencilKit drawing tool for creating image embeds from the Apple composer.
// Mirrors the web canvas with white drawing space, bottom tools, zoom, and undo.
// The dot grid is presentation-only and is excluded from the exported JPEG.
// Fullscreen delegates to the owning composer so rotation recalculates geometry.
// Drawing data remains local until the user explicitly completes the sketch.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/enter_message/SketchView.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

#if os(iOS)
import PencilKit

struct SketchComposerOverlay: View {
    @Binding var isFullscreen: Bool
    let onSave: (Data, String) -> Void
    let onCancel: () -> Void

    @State private var canvasView = PKCanvasView()
    @State private var selectedColor = UIColor.black
    @State private var selectedWidth: CGFloat = 5
    @State private var isErasing = false
    @State private var hasDrawing = false
    @State private var zoomScale: CGFloat = 1

    private let colors: [UIColor] = [
        .black, .white, .systemRed, .systemOrange,
        .systemYellow, .systemGreen, .systemBlue, .systemPurple,
    ]
    private let widths: [CGFloat] = [2, 5, 10, 20]

    var body: some View {
        ZStack(alignment: .topTrailing) {
            VStack(spacing: 0) {
                ZStack {
                    SketchDotGrid()
                    CanvasRepresentable(
                        canvasView: $canvasView,
                        selectedColor: selectedColor,
                        selectedWidth: selectedWidth,
                        isErasing: isErasing,
                        hasDrawing: $hasDrawing,
                        zoomScale: zoomScale
                    )
                }
                .background(Color.white)

                toolbar
            }

            Button { isFullscreen.toggle() } label: {
                Icon(isFullscreen ? "minimize" : "fullscreen", size: 18)
                    .foregroundStyle(Color.fontPrimary)
                    .frame(width: 32, height: 32)
                    .background(Color.white.opacity(0.9))
                    .clipShape(RoundedRectangle(cornerRadius: .radius3))
            }
            .buttonStyle(.plain)
            .padding(.top, 10)
            .padding(.trailing, 12)
            .accessibilityLabel(isFullscreen ? AppStrings.exitFullscreen : AppStrings.enterFullscreen)
            .accessibilityIdentifier("sketch-fullscreen-button")
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: 24))
        .clipped()
    }

    private var toolbar: some View {
        HStack(spacing: .spacing4) {
            Button(action: onCancel) {
                Icon("close", size: 20).foregroundStyle(Color.fontSecondary)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(AppStrings.close)

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: .spacing3) {
                    toolButton(
                        icon: "modify",
                        label: AppStrings.sketchPen,
                        identifier: "sketch-pen-button",
                        active: !isErasing
                    ) { isErasing = false }
                    toolButton(
                        icon: "eraser",
                        label: AppStrings.sketchEraser,
                        identifier: "sketch-eraser-button",
                        active: isErasing
                    ) { isErasing = true }

                    toolbarDivider

                    if !isErasing {
                        ForEach(colors, id: \.self) { color in
                            Button {
                                selectedColor = color
                            } label: {
                                Circle()
                                    .fill(Color(uiColor: color))
                                    .frame(width: 24, height: 24)
                                    .overlay {
                                        Circle().stroke(
                                            selectedColor == color ? Color.buttonPrimary : Color.grey30,
                                            lineWidth: selectedColor == color ? 3 : 1
                                        )
                                    }
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel(AppStrings.sketchAction)
                        }

                        toolbarDivider
                    }

                    ForEach(widths, id: \.self) { width in
                        Button { selectedWidth = width } label: {
                            Circle()
                                .fill(Color.fontPrimary)
                                .frame(width: min(width + 8, 28), height: min(width + 8, 28))
                                .frame(width: 32, height: 32)
                                .opacity(selectedWidth == width ? 1 : 0.35)
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("\(Int(width)) px")
                    }

                    toolbarDivider

                    zoomButton(
                        symbol: "−",
                        label: AppStrings.zoomOut,
                        identifier: "sketch-zoom-out-button",
                        action: { setZoom(zoomScale - 0.25) }
                    )
                    Button { setZoom(1) } label: {
                        Text("\(Int(zoomScale * 100))%")
                            .font(.omMicro.weight(.semibold))
                            .foregroundStyle(Color.fontPrimary)
                            .frame(minWidth: 42, minHeight: 32)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(AppStrings.resetZoom)
                    .accessibilityIdentifier("sketch-zoom-reset-button")
                    zoomButton(
                        symbol: "+",
                        label: AppStrings.zoomIn,
                        identifier: "sketch-zoom-in-button",
                        action: { setZoom(zoomScale + 0.25) }
                    )

                    toolbarDivider

                    toolButton(
                        icon: "undo",
                        label: AppStrings.sketchUndo,
                        identifier: "sketch-undo-button",
                        active: false
                    ) {
                        canvasView.undoManager?.undo()
                        hasDrawing = !canvasView.drawing.strokes.isEmpty
                    }
                    .disabled(!hasDrawing)

                    toolButton(
                        icon: "delete",
                        label: AppStrings.sketchClear,
                        identifier: "sketch-clear-button",
                        active: false
                    ) {
                        canvasView.drawing = PKDrawing()
                        hasDrawing = false
                    }
                }
                .padding(.horizontal, .spacing2)
            }

            Button(action: saveAndSend) {
                Text(AppStrings.sketchDone)
                    .font(.omSmall.weight(.semibold))
                    .foregroundStyle(Color.fontButton)
                    .padding(.horizontal, .spacing8)
                    .frame(height: 40)
                    .background(hasDrawing ? Color.buttonPrimary : Color.grey30)
                    .clipShape(RoundedRectangle(cornerRadius: .radius8))
            }
            .buttonStyle(.plain)
            .disabled(!hasDrawing)
            .accessibilityIdentifier("sketch-save-button")
        }
        .padding(.horizontal, .spacing5)
        .frame(height: 53)
        .background(Color.grey0)
    }

    private var toolbarDivider: some View {
        Rectangle().fill(Color.grey30).frame(width: 1, height: 24)
    }

    private func toolButton(
        icon: String,
        label: String,
        identifier: String,
        active: Bool,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Icon(icon, size: 18)
                .foregroundStyle(active ? Color.fontButton : Color.fontSecondary)
                .frame(width: 32, height: 32)
                .background(active ? Color.buttonPrimary : Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius3))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
        .accessibilityIdentifier(identifier)
    }

    private func zoomButton(
        symbol: String,
        label: String,
        identifier: String,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Text(symbol)
                .font(.omP.weight(.semibold))
                .foregroundStyle(Color.fontPrimary)
                .frame(width: 32, height: 32)
                .background(Color.grey10)
                .clipShape(RoundedRectangle(cornerRadius: .radius3))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
        .accessibilityIdentifier(identifier)
    }

    private func setZoom(_ value: CGFloat) {
        zoomScale = min(max(value, 0.5), 2)
    }

    private func saveAndSend() {
        guard hasDrawing else { return }
        let canvasSize = CGSize(
            width: max(canvasView.bounds.width, 1_200),
            height: max(canvasView.bounds.height, 900)
        )
        let bounds = CGRect(origin: .zero, size: canvasSize)
        let drawingImage = canvasView.drawing.image(from: bounds, scale: 1)
        let renderer = UIGraphicsImageRenderer(size: canvasSize)
        let image = renderer.image { context in
            UIColor.white.setFill()
            context.fill(bounds)
            drawingImage.draw(in: bounds)
        }
        guard let data = image.jpegData(compressionQuality: 0.92) else { return }
        let filename = "sketch-\(ISO8601DateFormatter().string(from: Date())).jpg"
        onSave(data, filename)
    }
}

private struct SketchDotGrid: View {
    var body: some View {
        Canvas { context, size in
            let spacing: CGFloat = 20
            for x in stride(from: spacing, through: size.width, by: spacing) {
                for y in stride(from: spacing, through: size.height, by: spacing) {
                    context.fill(
                        Path(ellipseIn: CGRect(x: x, y: y, width: 2, height: 2)),
                        with: .color(Color.grey30)
                    )
                }
            }
        }
        .background(Color.white)
        .allowsHitTesting(false)
    }
}

struct SketchView: View {
    @Binding var isFullscreen: Bool
    let onSave: (Data, String) -> Void
    let onCancel: () -> Void

    var body: some View {
        SketchComposerOverlay(
            isFullscreen: $isFullscreen,
            onSave: onSave,
            onCancel: onCancel
        )
    }
}

struct CanvasRepresentable: UIViewRepresentable {
    @Binding var canvasView: PKCanvasView
    let selectedColor: UIColor
    let selectedWidth: CGFloat
    let isErasing: Bool
    @Binding var hasDrawing: Bool
    let zoomScale: CGFloat

    func makeCoordinator() -> Coordinator {
        Coordinator(hasDrawing: $hasDrawing)
    }

    func makeUIView(context: Context) -> PKCanvasView {
        canvasView.drawingPolicy = .anyInput
        canvasView.backgroundColor = .clear
        canvasView.isOpaque = false
        canvasView.minimumZoomScale = 0.5
        canvasView.maximumZoomScale = 2
        canvasView.delegate = context.coordinator
        canvasView.accessibilityIdentifier = "sketch-canvas"
        updateTool(canvasView)
        return canvasView
    }

    func updateUIView(_ uiView: PKCanvasView, context: Context) {
        updateTool(uiView)
        if abs(uiView.zoomScale - zoomScale) > 0.01 {
            uiView.setZoomScale(zoomScale, animated: true)
        }
    }

    private func updateTool(_ canvas: PKCanvasView) {
        canvas.tool = isErasing
            ? PKEraserTool(.vector)
            : PKInkingTool(.pen, color: selectedColor, width: selectedWidth)
    }

    final class Coordinator: NSObject, PKCanvasViewDelegate {
        private let hasDrawing: Binding<Bool>

        init(hasDrawing: Binding<Bool>) {
            self.hasDrawing = hasDrawing
        }

        func canvasViewDrawingDidChange(_ canvasView: PKCanvasView) {
            hasDrawing.wrappedValue = !canvasView.drawing.strokes.isEmpty
        }
    }
}
#endif
