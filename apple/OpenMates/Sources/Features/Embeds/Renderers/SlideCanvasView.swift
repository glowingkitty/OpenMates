// SlideCanvasView — read-only drawing of one slide of a slides deck embed.
// The slide lives on a fixed 1920-unit-wide canvas that is scaled uniformly to
// the available width; elements arrive from the Rust core fully placed (layout
// slots applied) as `SlideRecord`, so no markup parsing or layout happens here.
// Specification: specifications/features/slides/specification.yml
// Assertions: slides.render.preview-and-fullscreen

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/slides/SlideCanvas.svelte
// CSS:     frontend/packages/ui/src/components/embeds/slides/SlideCanvas.svelte
// Layout:  frontend/packages/ui/src/components/embeds/slides/slidesTemplates.ts
// Tokens:  ColorTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

/// Maps template colour tokens (`plain` template) to design tokens.
enum SlideTemplateColors {
    static func color(_ value: String?) -> Color? {
        guard let value, !value.isEmpty else { return nil }
        switch value {
        case "background": return Color.grey0
        case "foreground": return Color.fontPrimary
        case "accent", "accent-2": return Color.buttonPrimary
        case "muted": return Color.fontSecondary
        case "surface": return Color.grey20
        default: return hex(value)
        }
    }

    /// `#rgb` / `#rrggbb` values from slide markup (author-chosen colours).
    static func hex(_ value: String) -> Color? {
        guard value.hasPrefix("#") else { return nil }
        var digits = String(value.dropFirst())
        if digits.count == 3 { digits = digits.map { "\($0)\($0)" }.joined() }
        guard digits.count == 6, let number = UInt32(digits, radix: 16) else { return nil }
        return Color(
            red: Double((number >> 16) & 0xFF) / 255,
            green: Double((number >> 8) & 0xFF) / 255,
            blue: Double(number & 0xFF) / 255)
    }
}

@MainActor struct SlideCanvasView: View {
    let slide: SlideRecord
    let width: CGFloat
    let height: CGFloat
    /// Build steps shown so far; elements with a higher step are hidden.
    var step: Int = 99

    private var visible: [SlideElementRecord] {
        slide.elements.filter { element in
            Int(element.step) <= step
                && !((element.kind == .notepad || element.kind == .todo) && element.hidden)
        }
    }

    var body: some View {
        GeometryReader { proxy in
            let scale = width > 0 ? proxy.size.width / width : 0
            ZStack(alignment: .topLeading) {
                ForEach(visible, id: \.id) { element in
                    SlideElementView(element: element)
                        .frame(width: CGFloat(element.w), height: CGFloat(element.h), alignment: .topLeading)
                        .offset(x: CGFloat(element.x), y: CGFloat(element.y))
                }
            }
            .frame(width: width, height: height, alignment: .topLeading)
            .background(Color.grey0)
            .clipped()
            .scaleEffect(scale, anchor: .topLeading)
            .frame(width: proxy.size.width, height: proxy.size.height, alignment: .topLeading)
        }
        .aspectRatio(width / height, contentMode: .fit)
        .overlay(Rectangle().stroke(Color.grey40, lineWidth: 1).allowsHitTesting(false))
        .clipped()
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("slide-canvas")
    }
}

/// One element in canvas units (the parent frames and offsets it).
@MainActor private struct SlideElementView: View {
    let element: SlideElementRecord

    // Canvas units scale with the slide, so sizes are explicit canvas-unit fonts.
    private func font(_ size: CGFloat) -> Font { .custom("Lexend Deca", size: size) }

    var body: some View {
        switch element.kind {
        case .text: textBody
        case .image: placeholder(icon: "image")
        case .video: placeholder(icon: nil)
        case .shape: shape
        case .notepad: card { if !element.text.isEmpty { Text(element.text).font(font(32)).foregroundStyle(Color.fontPrimary) } }
        case .todo: card { todoItems }
        case .link:
            Text(element.text)
                .font(font(36))
                .underline()
                .foregroundStyle(Color.buttonPrimary)
        case .block: placeholder(icon: nil)
        }
    }

    private var textBody: some View {
        var attributed = AttributedString()
        for run in element.runs {
            var piece = AttributedString(run.text)
            var intent: InlinePresentationIntent = []
            if run.bold { intent.insert(.stronglyEmphasized) }
            if run.italic || element.italic { intent.insert(.emphasized) }
            if !intent.isEmpty { piece.inlinePresentationIntent = intent }
            if run.underline { piece.underlineStyle = .single }
            if run.strike { piece.strikethroughStyle = .single }
            attributed.append(piece)
        }
        let family = element.fontFamily ?? "Lexend Deca"
        return Text(attributed)
            .font(.custom(family, size: CGFloat(element.fontSize)))
            .fontWeight(element.bold ? .bold : .regular)
            .foregroundStyle(SlideTemplateColors.color(element.color) ?? Color.fontPrimary)
            .multilineTextAlignment(alignment)
            .lineSpacing(CGFloat(element.fontSize) * 0.25)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: frameAlignment)
            .accessibilityIdentifier("slide-text")
    }

    private var alignment: TextAlignment {
        switch element.align {
        case "center": return .center
        case "right": return .trailing
        default: return .leading
        }
    }

    private var frameAlignment: Alignment {
        switch element.align {
        case "center": return .top
        case "right": return .topTrailing
        default: return .topLeading
        }
    }

    @ViewBuilder private var shape: some View {
        let fill = SlideTemplateColors.color(element.color) ?? Color.buttonPrimary
        let stroke = SlideTemplateColors.color(element.stroke)
        switch element.shapeKind {
        case "line":
            Rectangle().fill(stroke ?? fill).frame(height: 6).frame(maxHeight: .infinity, alignment: .center)
        case "ellipse":
            Ellipse().fill(fill).overlay(Ellipse().stroke(stroke ?? .clear, lineWidth: 6))
        case "triangle":
            SlideTriangle().fill(fill)
        default:
            Rectangle().fill(fill).overlay(Rectangle().stroke(stroke ?? .clear, lineWidth: 6))
        }
    }

    private func placeholder(icon: String?) -> some View {
        ZStack {
            Color.grey20
            if let icon {
                Icon(icon, size: 120).foregroundStyle(Color.fontSecondary)
            } else {
                SlideTriangle().rotation(.degrees(90)).fill(Color.fontSecondary).frame(width: 100, height: 120)
            }
        }
        .accessibilityLabel(element.alt.isEmpty ? element.title : element.alt)
    }

    private func card<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(element.title).font(font(32).weight(.bold)).foregroundStyle(Color.fontPrimary)
            content()
            Spacer(minLength: 0)
        }
        .padding(24)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Color.grey20)
        .clipShape(RoundedRectangle(cornerRadius: 16))
    }

    private var todoItems: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(Array(element.items.enumerated()), id: \.offset) { _, item in
                HStack(spacing: 16) {
                    Text(item.done ? "✓" : "")
                        .font(font(24))
                        .frame(width: 32, height: 32)
                        .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.fontSecondary, lineWidth: 3))
                    Text(item.label)
                        .font(font(32))
                        .strikethrough(item.done)
                        .foregroundStyle(item.done ? Color.fontSecondary : Color.fontPrimary)
                }
            }
        }
    }
}

private struct SlideTriangle: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: rect.midX, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY))
        path.addLine(to: CGPoint(x: rect.minX, y: rect.maxY))
        path.closeSubpath()
        return path
    }
}
