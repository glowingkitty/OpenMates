// Mind Maps direct embed renderer for Apple clients.
// Normalizes canonical OpenMates mind map JSON at the render boundary,
// recovers valid nodes and edges, and makes invalid content visible.
// Keeps the native surface aligned with the web Mind Maps embed contract.
// Specification: specifications/features/chats/specification.yml
// Assertions: chats.surface.semantic-parity

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/mindmaps/MindMapEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/mindmaps/MindMapEmbedFullscreen.svelte
// CSS:     frontend/packages/ui/src/components/embeds/mindmaps/MindMapEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/mindmaps/MindMapEmbedFullscreen.svelte
// Layout:  frontend/packages/ui/src/components/embeds/mindmaps/MindMapCanvas.svelte
//          frontend/packages/ui/src/components/embeds/mindmaps/mindMapContent.ts
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import Foundation
import SwiftUI

@MainActor struct MindMapEmbedRenderer: View {
    static func headerCounts(data: [String: AnyCodable]?) -> String {
        let map = NativeMindMapNormalizer.normalize(data: data)
        return "\(map.nodeCount) nodes · \(map.edgeCount) edges"
    }

    enum Constants {
        static let nodeWidth: CGFloat = 220
        static let nodeHeight: CGFloat = 64
        static let columnGap: CGFloat = 260
        static let rowGap: CGFloat = 130
        static let minZoom: CGFloat = 0.35
        static let maxZoom: CGFloat = 2.5
    }

    let data: [String: AnyCodable]?
    let mode: EmbedDisplayMode
    private let normalized: NativeMindMapNormalization
    @State private var scale: CGFloat
    @State private var baseScale: CGFloat
    @State private var pan: CGSize
    @State private var dragStartPan: CGSize
    @State private var collapsedNodeIds: Set<String>
    @State private var cachedLayout: NativeMindMapLayout?
    @State private var cachedModel: NativeMindMapDocument?

    init(data: [String: AnyCodable]?, mode: EmbedDisplayMode) {
        self.data = data
        self.mode = mode
        let normalized = NativeMindMapNormalizer.normalize(data: data)
        self.normalized = normalized
        _scale = State(initialValue: 1)
        _baseScale = State(initialValue: 1)
        _pan = State(initialValue: .zero)
        _dragStartPan = State(initialValue: .zero)
        _collapsedNodeIds = State(initialValue: Set(normalized.model?.collapsedNodeIds ?? []))
        _cachedModel = State(initialValue: normalized.model)
        _cachedLayout = State(initialValue: normalized.model.map { NativeMindMapLayout(model: $0, collapsedNodeIds: Set($0.collapsedNodeIds)) })
    }

    var body: some View {
        switch mode {
        case .preview:
            preview
        case .fullscreen:
            fullscreen
        }
    }

    private var preview: some View {
        Group {
            if normalized.status == .invalidSource {
                Text(AppStrings.mindMapInvalidJSON)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let model = normalized.model {
                graphCanvas(model: model)
                    .allowsHitTesting(false)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("mindmap-rendered-preview")
    }

    private var fullscreen: some View {
        VStack(alignment: .leading, spacing: .spacing8) {
            if normalized.status == .invalidSource {
                invalidSourceView
            } else if let model = normalized.model {
                graphCanvas(model: model)
                if normalized.status == .partial {
                    warningsView
                }
            }

            if normalized.status == .invalidSource { sourceView }
        }
        .padding(.spacing8)
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }

    private var invalidSourceView: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Text(AppStrings.mindMapInvalidJSON)
                .font(.omP.weight(.bold))
                .foregroundStyle(Color.error)
            if let parseError = normalized.parseError {
                Text(parseError)
                    .font(.omSmall)
                    .foregroundStyle(Color.fontSecondary)
            }
        }
        .padding(.spacing8)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: .radius8))
        .overlay(RoundedRectangle(cornerRadius: .radius8).stroke(Color.grey20, lineWidth: 1))
    }

    private func graphCanvas(model: NativeMindMapDocument) -> some View {
        // A retained SwiftUI identity can receive streamed replacement content.
        // Select by the complete normalized model before the state refresh runs.
        let currentCollapsed = cachedModel == model ? collapsedNodeIds : Set(model.collapsedNodeIds)
        let layout = cachedModel == model
            ? cachedLayout ?? NativeMindMapLayout(model: model, collapsedNodeIds: currentCollapsed)
            : NativeMindMapLayout(model: model, collapsedNodeIds: currentCollapsed)
        return GeometryReader { proxy in
            ZStack(alignment: .topLeading) {
                mindMapGrid
                ZStack(alignment: .topLeading) {
                    Canvas { context, _ in
                        var path = Path()
                        for edge in layout.edges {
                            path.move(to: CGPoint(x: edge.source.x + Constants.nodeWidth / 2, y: edge.source.y + Constants.nodeHeight))
                            path.addCurve(
                                to: CGPoint(x: edge.target.x + Constants.nodeWidth / 2, y: edge.target.y),
                                control1: CGPoint(x: edge.source.x + Constants.nodeWidth / 2, y: edge.source.y + Constants.nodeHeight + 40),
                                control2: CGPoint(x: edge.target.x + Constants.nodeWidth / 2, y: edge.target.y - 40)
                            )
                        }
                        context.stroke(path, with: .color(Color.grey30), lineWidth: 2)
                    }
                    .frame(width: layout.width, height: layout.height)

                    ForEach(layout.nodes) { node in
                        mindMapNode(node, model: model, viewport: proxy.size)
                            .offset(x: node.x, y: node.y)
                            // The surviving node moves between a single-node stage
                            // and the tree. Refresh its stateless presentation so
                            // SwiftUI does not retain the collapsed layout/AX frame.
                            // ForEach and public accessibility IDs stay model-based.
                            .id(currentCollapsed.contains(node.id))
                    }
                }
                .frame(width: layout.width, height: layout.height, alignment: .topLeading)
                .scaleEffect(scale, anchor: .topLeading)
                .offset(pan)
            }
            // The stage's fixed unscaled width must not become the viewport's
            // layout width; otherwise floating controls center outside the screen.
            .frame(width: proxy.size.width, height: proxy.size.height, alignment: .topLeading)
            .contentShape(Rectangle())
            .gesture(panGesture)
            .simultaneousGesture(zoomGesture)
            .onAppear {
                fit(layout: layout, viewport: proxy.size)
            }
            .onChange(of: model, initial: true) { _, nextModel in
                let nextCollapsed = Set(nextModel.collapsedNodeIds)
                let next = NativeMindMapLayout(model: nextModel, collapsedNodeIds: nextCollapsed)
                cachedModel = nextModel
                collapsedNodeIds = nextCollapsed
                cachedLayout = next
                fit(layout: next, viewport: proxy.size)
            }
            .onChange(of: proxy.size) { _, viewport in
                fit(layout: layout, viewport: viewport)
            }
            .overlay(alignment: .bottom) {
                if mode == .fullscreen {
                    zoomControls(layout: layout, viewport: proxy.size)
                        .padding(.bottom, .spacing5)
                }
            }
        }
        .frame(minHeight: mode == .preview ? 0 : 490)
        .clipShape(RoundedRectangle(cornerRadius: mode == .preview ? .radius3 : .radius8))
        .overlay {
            if mode == .fullscreen {
                RoundedRectangle(cornerRadius: .radius8).stroke(Color.grey20, lineWidth: 1)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("mindmap-fullscreen-canvas")
        #if DEBUG
        .preference(key: NativeMindMapRenderedLayoutKey.self, value: layout)
        #endif
    }

    @ViewBuilder private var mindMapGrid: some View {
        if mode == .preview {
            // The rendered compact canvas inherits the preview card's grey panel.
            // Fullscreen retains its own dotted canvas and perimeter.
            Color.clear
        } else {
            ZStack {
                Color.grey5
                Canvas { context, size in
                    var dots = Path()
                    let step: CGFloat = 28
                    var x: CGFloat = 20
                    while x < size.width {
                        var y: CGFloat = 20
                        while y < size.height {
                            dots.addEllipse(in: CGRect(x: x, y: y, width: 2, height: 2))
                            y += step
                        }
                        x += step
                    }
                    context.fill(dots, with: .color(Color.grey20))
                }
            }
            .accessibilityHidden(true)
        }
    }

    private func mindMapNode(_ node: NativeMindMapViewNode, model: NativeMindMapDocument, viewport: CGSize) -> some View {
        let foreground = node.foreground
        return HStack(spacing: mode == .preview ? 6 : 8) {
            LucideNativeIcon(node.icon ?? "workflow", size: mode == .preview ? 10 : 14)
                .frame(width: 22, height: 22)
                .background(foreground.opacity(0.14), in: Circle())
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
                Text(node.label)
                    .font(.omP.weight(.bold))
                    .fixedSize(horizontal: false, vertical: true)
                if let description = node.description {
                    Text(description)
                        .font(.omTiny)
                        .foregroundStyle(foreground.opacity(0.72))
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            if node.hasChildren && mode == .fullscreen {
                collapseButton(for: node, model: model, viewport: viewport)
            }
        }
        .foregroundStyle(foreground)
        .padding(.horizontal, mode == .preview ? 10 : 12)
        .padding(.vertical, mode == .preview ? 8 : 10)
        .frame(width: Constants.nodeWidth, alignment: .leading)
        .frame(minHeight: Constants.nodeHeight)
        .background(node.background)
        .clipShape(RoundedRectangle(cornerRadius: .radius5))
        .overlay(RoundedRectangle(cornerRadius: .radius5).stroke(node.border, lineWidth: 1))
        .shadow(color: .black.opacity(0.08), radius: 10, x: 0, y: 8)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("mindmap-node-\(node.id)")
        .help(Text(node.label))
        .accessibilityLabel(node.label)
    }

    private func collapseButton(for node: NativeMindMapViewNode, model: NativeMindMapDocument, viewport: CGSize) -> some View {
        Button {
            var nextCollapsed = collapsedNodeIds
            if nextCollapsed.contains(node.id) {
                nextCollapsed.remove(node.id)
            } else {
                nextCollapsed.insert(node.id)
            }
            // Commit the visibility set and its geometry in one render update.
            // An onChange callback exposes the previous cached tree for one frame.
            let next = NativeMindMapLayout(model: model, collapsedNodeIds: nextCollapsed)
            collapsedNodeIds = nextCollapsed
            cachedLayout = next
            fit(layout: next, viewport: viewport)
        } label: {
            Text(collapsedNodeIds.contains(node.id) ? "+" : "−")
                .font(.omSmall.weight(.bold))
                .foregroundStyle(node.foreground)
                .frame(width: 24, height: 24)
                .background(node.foreground.opacity(0.08))
                .clipShape(Circle())
                .overlay(Circle().stroke(node.foreground.opacity(0.24), lineWidth: 1))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("mindmap-collapse-\(node.id)")
        .help(Text(collapsedNodeIds.contains(node.id) ? AppStrings.mindMapExpand(node.label) : AppStrings.mindMapCollapse(node.label)))
        .accessibilityLabel(collapsedNodeIds.contains(node.id) ? AppStrings.mindMapExpand(node.label) : AppStrings.mindMapCollapse(node.label))
    }

    private func zoomControls(layout: NativeMindMapLayout, viewport: CGSize) -> some View {
        HStack(spacing: .spacing2) {
            OMIconButton(icon: "minus", label: AppStrings.zoomOut, size: 36, iconSize: 16) {
                zoom(by: 0.85, viewport: viewport)
            }
            .disabled(scale <= Constants.minZoom)
            .accessibilityIdentifier("mindmap-zoom-out")
            Button { fit(layout: layout, viewport: viewport) } label: {
                Text("\(Int((scale * 100).rounded()))%")
                    .font(.omTiny.weight(.medium))
                    .foregroundStyle(Color.grey80)
                    .frame(minWidth: 52, minHeight: 32)
                    .background(Color.grey5, in: RoundedRectangle(cornerRadius: .radius7))
                    .overlay(RoundedRectangle(cornerRadius: .radius7).stroke(Color.grey20, lineWidth: 1))
            }
            .buttonStyle(.plain)
            .accessibilityLabel(AppStrings.resetZoom)
            .accessibilityIdentifier("mindmap-zoom-reset")
            OMIconButton(icon: "plus", label: AppStrings.zoomIn, size: 36, iconSize: 16) {
                zoom(by: 1.15, viewport: viewport)
            }
            .disabled(scale >= Constants.maxZoom)
            .accessibilityIdentifier("mindmap-zoom-in")
        }
        .padding(.vertical, .spacing2)
        .padding(.horizontal, .spacing3)
        .background(Color.grey0, in: Capsule())
        .shadow(color: .black.opacity(0.15), radius: 4, y: 2)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("mindmap-zoom-controls")
    }

    private func zoom(by multiplier: CGFloat, viewport: CGSize) {
        let nextScale = min(Constants.maxZoom, max(Constants.minZoom, scale * multiplier))
        let ratio = nextScale / scale
        pan = CGSize(width: viewport.width / 2 - (viewport.width / 2 - pan.width) * ratio,
                     height: viewport.height / 2 - (viewport.height / 2 - pan.height) * ratio)
        scale = nextScale
        baseScale = nextScale
        dragStartPan = pan
    }

    private var warningsView: some View {
        VStack(alignment: .leading, spacing: .spacing3) {
            Text(AppStrings.mindMapValidationWarnings)
                .font(.omP.weight(.bold))
                .foregroundStyle(Color.fontPrimary)
            ForEach(normalized.warnings, id: \.self) { warning in
                Text(warning)
                    .font(.omTiny)
                    .foregroundStyle(Color.fontSecondary)
            }
        }
        .padding(.spacing8)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: .radius8))
        .overlay(RoundedRectangle(cornerRadius: .radius8).stroke(Color.grey20, lineWidth: 1))
    }

    private var sourceView: some View {
        VStack(alignment: .leading, spacing: .spacing4) {
            Text(AppStrings.mindMapSource)
                .font(.omP.weight(.bold))
                .foregroundStyle(Color.fontPrimary)
            Text(normalized.sourceJSON)
                .font(.omMicro)
                .foregroundStyle(Color.fontSecondary)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .padding(.spacing8)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: .radius8))
        .overlay(RoundedRectangle(cornerRadius: .radius8).stroke(Color.grey20, lineWidth: 1))
    }

    private var panGesture: some Gesture {
        DragGesture()
            .onChanged { value in
                pan = CGSize(width: dragStartPan.width + value.translation.width, height: dragStartPan.height + value.translation.height)
            }
            .onEnded { _ in
                dragStartPan = pan
            }
    }

    private var zoomGesture: some Gesture {
        MagnificationGesture()
            .onChanged { value in
                scale = min(Constants.maxZoom, max(Constants.minZoom, baseScale * value))
            }
            .onEnded { _ in
                baseScale = scale
            }
    }

    private func fit(layout: NativeMindMapLayout, viewport: CGSize) {
        guard layout.width > 0, layout.height > 0, viewport.width > 0, viewport.height > 0 else { return }
        let nextScale = mode == .preview
            ? min(viewport.width / layout.width, viewport.height / layout.height, 1.1)
            : min(
            Constants.maxZoom,
            max(Constants.minZoom, min((viewport.width - 80) / layout.width, (viewport.height - 120) / layout.height, 1.2))
        )
        scale = nextScale
        baseScale = nextScale
        pan = CGSize(
            width: ((viewport.width - layout.width * nextScale) / 2).rounded(),
            height: ((viewport.height - layout.height * nextScale) / 2).rounded()
        )
        dragStartPan = pan
    }
}

private enum NativeMindMapStatus {
    case valid
    case partial
    case invalidSource
}

struct NativeMindMapNode: Identifiable, Equatable {
    let id: String
    let label: String
    let description: String?
    var icon: String? = nil
    var color: String? = nil
    let children: [String]
}

struct NativeMindMapEdge: Equatable {
    let source: String
    let target: String
    var type: String? = nil
    var label: String? = nil
}

struct NativeMindMapDocument: Equatable {
    let title: String
    let rootId: String
    let nodes: [NativeMindMapNode]
    let edges: [NativeMindMapEdge]
    let collapsedNodeIds: [String]
    var layout: String = "radial-tree"
}

@MainActor enum NativeMindMapPreviewTitle {
    static func resolve(_ data: [String: AnyCodable]?) -> String {
        // Match the web preview's default title prop. Only an explicitly empty
        // title falls back to the normalized document title.
        let title = data?["title"]?.value as? String ?? AppStrings.mindMap
        if !title.isEmpty { return title }
        return NativeMindMapNormalizer.normalize(data: data).model?.title ?? AppStrings.mindMap
    }
}

@MainActor private struct NativeMindMapNormalization {
    let status: NativeMindMapStatus
    let model: NativeMindMapDocument?
    let sourceJSON: String
    let title: String
    let nodeCount: Int
    let edgeCount: Int
    let warnings: [String]
    let parseError: String?

    func outline(maxNodes: Int) -> String {
        guard let model else { return AppStrings.mindMapInvalidJSON }
        let nodesById = Dictionary(uniqueKeysWithValues: model.nodes.map { ($0.id, $0) })
        var lines: [String] = []
        var visited = Set<String>()

        func visit(_ nodeId: String, depth: Int) {
            guard visited.count < maxNodes, !visited.contains(nodeId), let node = nodesById[nodeId] else { return }
            visited.insert(nodeId)
            lines.append("\(String(repeating: "  ", count: depth))- \(node.label)")
            for child in node.children {
                visit(child, depth: depth + 1)
            }
        }

        visit(model.rootId, depth: 0)
        for node in model.nodes where visited.count < maxNodes && !visited.contains(node.id) {
            visit(node.id, depth: 0)
        }
        return lines.joined(separator: "\n")
    }
}

@MainActor private enum NativeMindMapNormalizer {
    static func normalize(data: [String: AnyCodable]?) -> NativeMindMapNormalization {
        let sourceValue = data?["source_json"]?.value ?? data?["model"]?.value
        let parsed = parse(sourceValue)
        guard parsed.ok, let raw = parsed.value as? [String: Any] else {
            return invalidSource(sourceJSON: parsed.sourceJSON, parseError: parsed.error ?? AppStrings.mindMapInvalidJSON)
        }
        guard raw["openmatesType"] as? String == "mindmap" else {
            return invalidSource(sourceJSON: canonicalJSONString(raw), parseError: AppStrings.mindMapInvalidJSON)
        }
        guard raw["schemaVersion"] as? Int == 1 else {
            return invalidSource(sourceJSON: canonicalJSONString(raw), parseError: AppStrings.mindMapInvalidJSON)
        }

        let title = cleanString(raw["title"]) ?? AppStrings.mindMap
        let rootIdCandidate = cleanString(raw["rootId"]) ?? ""
        guard let rawNodes = raw["nodes"] as? [Any], !rawNodes.isEmpty else {
            return invalidSource(sourceJSON: canonicalJSONString(raw), parseError: AppStrings.mindMapInvalidJSON)
        }

        var warnings: [String] = []
        var nodes: [NativeMindMapNode] = []
        var seenIds = Set<String>()
        for (index, item) in rawNodes.enumerated() {
            guard let node = item as? [String: Any] else {
                warnings.append("invalid_node: nodes[\(index)]")
                continue
            }
            guard let id = cleanString(node["id"]) else {
                warnings.append("missing_node_id: nodes[\(index)].id")
                continue
            }
            guard !seenIds.contains(id) else {
                warnings.append("duplicate_node_id: nodes[\(index)].id")
                continue
            }
            seenIds.insert(id)
            var label = cleanString(node["label"])
            if label == nil {
                warnings.append("missing_label: nodes[\(index)].label")
                label = AppStrings.mindMapInvalidContent
            }
            let children = (node["children"] as? [Any])?.compactMap(cleanString) ?? []
            nodes.append(NativeMindMapNode(id: id, label: label ?? AppStrings.mindMapInvalidContent, description: cleanString(node["description"]), icon: cleanString(node["icon"]), color: normalizeColor(node["color"]), children: children))
        }
        guard !nodes.isEmpty else {
            return invalidSource(sourceJSON: canonicalJSONString(raw), parseError: AppStrings.mindMapInvalidJSON)
        }

        let knownIds = Set(nodes.map(\.id))
        var rootId = rootIdCandidate
        if !knownIds.contains(rootId) {
            warnings.append("missing_root: rootId")
            rootId = nodes[0].id
        }
        nodes = nodes.map { node in
            let filteredChildren = node.children.filter { knownIds.contains($0) }
            if filteredChildren.count != node.children.count {
                warnings.append("missing_child: nodes.\(node.id).children")
            }
            return NativeMindMapNode(id: node.id, label: node.label, description: node.description, icon: node.icon, color: node.color, children: filteredChildren)
        }

        let edges = normalizeEdges(raw["edges"], knownIds: knownIds, warnings: &warnings)
        let collapsed = ((raw["view"] as? [String: Any])?["collapsedNodeIds"] as? [Any])?.compactMap(cleanString) ?? []
        let model = NativeMindMapDocument(title: title, rootId: rootId, nodes: nodes, edges: edges, collapsedNodeIds: collapsed,
                                         layout: cleanString((raw["view"] as? [String: Any])?["layout"]) ?? "radial-tree")
        return NativeMindMapNormalization(
            status: warnings.isEmpty ? .valid : .partial,
            model: model,
            sourceJSON: canonicalJSONString(raw),
            title: title,
            nodeCount: nodes.count,
            edgeCount: edges.count,
            warnings: warnings,
            parseError: nil
        )
    }

    private static func normalizeColor(_ value: Any?) -> String? {
        guard let value = cleanString(value), value.range(of: "^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$", options: .regularExpression) != nil else { return nil }
        return value
    }

    private static func normalizeEdges(_ value: Any?, knownIds: Set<String>, warnings: inout [String]) -> [NativeMindMapEdge] {
        guard let rawEdges = value as? [Any] else { return [] }
        var edges: [NativeMindMapEdge] = []
        for (index, item) in rawEdges.enumerated() {
            guard let edge = item as? [String: Any] else {
                warnings.append("invalid_edge: edges[\(index)]")
                continue
            }
            guard let source = cleanString(edge["source"]), knownIds.contains(source) else {
                warnings.append("missing_edge_source: edges[\(index)].source")
                continue
            }
            guard let target = cleanString(edge["target"]), knownIds.contains(target) else {
                warnings.append("missing_edge_target: edges[\(index)].target")
                continue
            }
            edges.append(NativeMindMapEdge(source: source, target: target, type: cleanString(edge["type"]), label: cleanString(edge["label"])))
        }
        return edges
    }

    private static func parse(_ value: Any?) -> (ok: Bool, value: Any?, sourceJSON: String, error: String?) {
        if let source = value as? String {
            guard let data = source.data(using: .utf8) else {
                return (false, nil, source, AppStrings.mindMapInvalidJSON)
            }
            do {
                return (true, try JSONSerialization.jsonObject(with: data), source, nil)
            } catch {
                return (false, nil, source, "\(AppStrings.mindMapInvalidJSON): \(error.localizedDescription)")
            }
        }
        if let raw = value as? [String: Any] {
            return (true, raw, canonicalJSONString(raw), nil)
        }
        return (false, nil, "", AppStrings.mindMapInvalidJSON)
    }

    private static func invalidSource(sourceJSON: String, parseError: String) -> NativeMindMapNormalization {
        NativeMindMapNormalization(
            status: .invalidSource,
            model: nil,
            sourceJSON: sourceJSON,
            title: AppStrings.mindMapInvalidJSON,
            nodeCount: 0,
            edgeCount: 0,
            warnings: [],
            parseError: parseError
        )
    }

    private static func cleanString(_ value: Any?) -> String? {
        guard let value = value as? String else { return nil }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    private static func canonicalJSONString(_ value: Any) -> String {
        guard JSONSerialization.isValidJSONObject(value),
              let data = try? JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys]),
              let string = String(data: data, encoding: .utf8) else {
            return ""
        }
        return string + "\n"
    }
}

struct NativeMindMapViewNode: Identifiable, Equatable {
    let id: String
    let label: String
    let description: String?
    let icon: String?
    let color: String?
    let x: CGFloat
    let y: CGFloat
    let hasChildren: Bool

    private var rgba: (Double, Double, Double, Double)? {
        guard let color else { return nil }
        let hex = String(color.dropFirst())
        let expanded = hex.count == 3 ? hex.map { "\($0)\($0)" }.joined() : hex
        guard let value = UInt32(expanded, radix: 16) else { return nil }
        let rgb = expanded.count == 8 ? value >> 8 : value
        return (Double((rgb >> 16) & 255), Double((rgb >> 8) & 255), Double(rgb & 255), expanded.count == 8 ? Double(value & 255) / 255 : 1)
    }
    var background: Color {
        guard let (r, g, b, a) = rgba else { return .grey0 }
        return Color(.sRGB, red: r / 255, green: g / 255, blue: b / 255, opacity: a)
    }
    var border: Color { color == nil ? .grey20 : background }
    var foreground: Color {
        guard let (r, g, b, a) = rgba else { return .fontPrimary }
        let luminance = (0.299 * (r * a + 250 * (1 - a)) + 0.587 * (g * a + 250 * (1 - a)) + 0.114 * (b * a + 250 * (1 - a))) / 255
        return luminance > 0.58 ? .fontPrimary : .grey0
    }
}

struct NativeMindMapViewEdge: Equatable {
    let source: NativeMindMapViewNode
    let target: NativeMindMapViewNode
}

struct NativeMindMapLayout: Equatable {
    let nodes: [NativeMindMapViewNode]
    let edges: [NativeMindMapViewEdge]
    let width: CGFloat
    let height: CGFloat

    init(model: NativeMindMapDocument, collapsedNodeIds: Set<String>) {
        let nodesById = Dictionary(uniqueKeysWithValues: model.nodes.map { ($0.id, $0) })
        var visited = Set<String>()
        var viewNodes: [NativeMindMapViewNode] = []
        var nextColumn: CGFloat = 0
        var hidden = Set<String>()
        func hideDescendants(_ nodeId: String) {
            guard let node = nodesById[nodeId] else { return }
            for child in node.children where !hidden.contains(child) {
                hidden.insert(child)
                hideDescendants(child)
            }
        }

        @discardableResult
        func visit(_ nodeId: String, depth: CGFloat) -> NativeMindMapViewNode? {
            guard let node = nodesById[nodeId], !visited.contains(nodeId), !hidden.contains(nodeId) else { return nil }
            visited.insert(nodeId)
            let childIds = node.children.filter { nodesById[$0] != nil }
            var childViews: [NativeMindMapViewNode] = []
            if collapsedNodeIds.contains(nodeId) {
                hideDescendants(nodeId)
            } else {
                for childId in childIds {
                    if let child = visit(childId, depth: depth + 1) {
                        childViews.append(child)
                    }
                }
            }
            let column: CGFloat
            if childViews.isEmpty {
                column = nextColumn
                nextColumn += 1
            } else {
                column = childViews.reduce(0) { $0 + $1.x } / CGFloat(childViews.count) / MindMapEmbedRenderer.Constants.columnGap
            }
            let viewNode = NativeMindMapViewNode(
                id: node.id,
                label: node.label,
                description: node.description,
                icon: node.icon,
                color: node.color,
                x: column * MindMapEmbedRenderer.Constants.columnGap,
                y: depth * MindMapEmbedRenderer.Constants.rowGap,
                hasChildren: !childIds.isEmpty
            )
            viewNodes.append(viewNode)
            return viewNode
        }

        visit(model.rootId, depth: 0)
        for node in model.nodes where !visited.contains(node.id) {
            visit(node.id, depth: 0)
        }

        let visibleById = Dictionary(uniqueKeysWithValues: viewNodes.map { ($0.id, $0) })
        var viewEdges: [NativeMindMapViewEdge] = []
        for node in model.nodes where !collapsedNodeIds.contains(node.id) {
            guard let source = visibleById[node.id] else { continue }
            for childId in node.children {
                if let target = visibleById[childId] {
                    viewEdges.append(NativeMindMapViewEdge(source: source, target: target))
                }
            }
        }
        for edge in model.edges {
            if let source = visibleById[edge.source], let target = visibleById[edge.target] {
                viewEdges.append(NativeMindMapViewEdge(source: source, target: target))
            }
        }

        nodes = viewNodes
        edges = viewEdges
        width = max(viewNodes.map { $0.x + MindMapEmbedRenderer.Constants.nodeWidth }.max() ?? MindMapEmbedRenderer.Constants.nodeWidth, MindMapEmbedRenderer.Constants.nodeWidth)
        height = max(viewNodes.map { $0.y + MindMapEmbedRenderer.Constants.nodeHeight }.max() ?? MindMapEmbedRenderer.Constants.nodeHeight, MindMapEmbedRenderer.Constants.nodeHeight)
    }
}

#if DEBUG
// Lets mounted preview verification observe the selected layout, including retained
// SwiftUI state, without extracting private content from screenshots or logging it.
struct NativeMindMapRenderedLayoutKey: PreferenceKey {
    static var defaultValue: NativeMindMapLayout? { nil }
    static func reduce(value: inout NativeMindMapLayout?, nextValue: () -> NativeMindMapLayout?) {
        value = nextValue() ?? value
    }
}
#endif

// Web: MindMapEmbedFullscreen.svelte downloadMindMap/createMindMapBlob and
// mindMapContent.ts serializeMindMapDocument. The export is the normalized
// document; interactive collapse/zoom state does not mutate the source file.
@MainActor struct NativeMindMapDownloadFile: Equatable {
    let filename: String
    let content: String
    let mimeType = "application/json"

    static func build(data: [String: AnyCodable]?) -> Self {
        let normalized = NativeMindMapNormalizer.normalize(data: data)
        let title = data?["title"]?.value as? String ?? normalized.title
        let slug = title.lowercased()
            .replacingOccurrences(of: "[^a-z0-9]+", with: "-", options: .regularExpression)
            .trimmingCharacters(in: CharacterSet(charactersIn: "-"))
        let content: String
        if let model = normalized.model {
            let nodes: [[String: Any]] = model.nodes.map { node in
                var value: [String: Any] = ["id": node.id, "label": node.label]
                if let description = node.description { value["description"] = description }
                if let icon = node.icon { value["icon"] = icon }
                if let color = node.color { value["color"] = color }
                if !node.children.isEmpty { value["children"] = node.children }
                return value
            }
            let edges: [[String: Any]] = model.edges.map { edge in
                var value: [String: Any] = ["source": edge.source, "target": edge.target]
                if let type = edge.type { value["type"] = type }
                if let label = edge.label { value["label"] = label }
                return value
            }
            let document: [String: Any] = ["openmatesType": "mindmap", "schemaVersion": 1,
                "title": model.title, "rootId": model.rootId, "nodes": nodes, "edges": edges,
                "view": ["layout": model.layout, "collapsedNodeIds": model.collapsedNodeIds]]
            let encoded = try? JSONSerialization.data(withJSONObject: document, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
            content = encoded.flatMap { String(data: $0, encoding: .utf8) }.map { $0 + "\n" } ?? normalized.sourceJSON
        } else {
            content = normalized.sourceJSON
        }
        return Self(filename: (slug.isEmpty ? "mindmap" : slug) + ".ommindmap", content: content)
    }
}
