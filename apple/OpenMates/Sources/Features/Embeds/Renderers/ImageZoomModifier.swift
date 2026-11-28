// Web counterpart: frontend/apps/web_app/src/lib/actions/contentZoom.ts

import SwiftUI

/// Magnifies the image within its existing frame and leaves fit-size scrolling to its parent.
private struct ImageZoomModifier: ViewModifier {
    let onOpen: (() -> Void)?

    @State private var scale: CGFloat = 1
    @State private var offset: CGSize = .zero
    @State private var size: CGSize = .zero
    @GestureState private var magnification: CGFloat = 1
    @GestureState private var drag: CGSize = .zero

    func body(content: Content) -> some View {
        let visibleScale = boundedScale(scale * magnification)
        let visibleOffset = scaledOffset(visibleScale, drag: drag)
        content
            .scaleEffect(visibleScale)
            .offset(visibleOffset)
            .clipped()
            .contentShape(Rectangle())
            .onGeometryChange(for: CGSize.self) { $0.size } action: { size = $0 }
            .simultaneousGesture(pinch)
            .gesture(pan, including: scale > 1 ? .all : .subviews)
            .gesture(TapGesture().onEnded { _ in onOpen?() }, including: onOpen == nil ? .subviews : .all)
            .highPriorityGesture(doubleTap)
            .accessibilityElement(children: .combine)
            .accessibilityValue(Text("\(Int((scale * 100).rounded()))%"))
    }

    private var pinch: some Gesture {
        MagnifyGesture()
            .updating($magnification) { value, magnification, _ in
                magnification = value.magnification
            }
            .onEnded { value in
                let nextScale = boundedScale(scale * value.magnification)
                offset = scaledOffset(nextScale, drag: .zero)
                scale = nextScale
            }
    }

    private var pan: some Gesture {
        DragGesture()
            .updating($drag) { value, drag, _ in drag = value.translation }
            .onEnded { value in offset = scaledOffset(scale, drag: value.translation) }
    }

    private var doubleTap: some Gesture {
        SpatialTapGesture(count: 2).onEnded { tap in
            if scale > 1 {
                scale = 1
                offset = .zero
            } else {
                scale = 2
                offset = boundedOffset(CGSize(width: size.width / 2 - tap.location.x,
                                              height: size.height / 2 - tap.location.y), at: scale)
            }
        }
    }

    private func boundedScale(_ scale: CGFloat) -> CGFloat {
        min(4, max(1, scale))
    }

    private func scaledOffset(_ nextScale: CGFloat, drag: CGSize) -> CGSize {
        let ratio = nextScale / scale
        return boundedOffset(CGSize(width: offset.width * ratio + drag.width,
                                    height: offset.height * ratio + drag.height), at: nextScale)
    }

    private func boundedOffset(_ offset: CGSize, at scale: CGFloat) -> CGSize {
        let maxX = size.width * (scale - 1) / 2
        let maxY = size.height * (scale - 1) / 2
        return CGSize(width: min(maxX, max(-maxX, offset.width)),
                      height: min(maxY, max(-maxY, offset.height)))
    }
}

extension View {
    @ViewBuilder
    func imageZoom(onOpen: (() -> Void)? = nil) -> some View {
        let image = modifier(ImageZoomModifier(onOpen: onOpen))
        if let onOpen { image.accessibilityAction { onOpen() } }
        else { image }
    }
}
