// Mind Maps direct embed renderer for Apple clients.
// Normalizes canonical OpenMates mind map JSON at the render boundary,
// recovers valid nodes and edges, and makes invalid content visible.
// Keeps the native surface aligned with the web Mind Maps embed contract.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/embeds/mindmaps/MindMapEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/mindmaps/MindMapEmbedFullscreen.svelte
// CSS:     frontend/packages/ui/src/components/embeds/mindmaps/MindMapEmbedPreview.svelte
//          frontend/packages/ui/src/components/embeds/mindmaps/MindMapEmbedFullscreen.svelte
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import Foundation
import SwiftUI

struct MindMapEmbedRenderer: View {
    fileprivate enum Constants {
        static let nodeWidth: CGFloat = 180
        static let nodeHeight: CGFloat = 54
        static let columnGap: CGFloat = 260
        static let rowGap: CGFloat = 92
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
        VStack(alignment: .leading, spacing: .spacing4) {
            HStack(spacing: .spacing3) {
                Icon("diagram", size: 22)
                    .foregroundStyle(Color.buttonPrimary)
                Text(normalized.title)
                    .font(.omSmall.weight(.bold))
                    .foregroundStyle(Color.fontPrimary)
                    .lineLimit(1)
            }

            if normalized.status == .invalidSource {
                Text(AppStrings.mindMapInvalidJSON)
                    .font(.omXs)
                    .foregroundStyle(Color.error)
                    .lineLimit(2)
            } else {
                Text(normalized.outline(maxNodes: 12))
                    .font(.omTiny)
                    .foregroundStyle(Color.fontSecondary)
                    .lineLimit(8)
            }

            if normalized.status == .partial {
                Text(AppStrings.mindMapValidationWarnings)
                    .font(.omTiny)
                    .foregroundStyle(Color.warning)
                    .lineLimit(1)
            }
        }
        .padding(.spacing6)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(normalized.title), \(AppStrings.mindMapCounts(nodes: normalized.nodeCount, edges: normalized.edgeCount))")
    }

    private var fullscreen: some View {
        VStack(alignment: .leading, spacing: .spacing8) {
            HStack(spacing: .spacing4) {
                AppIconView(appId: "mindmaps", size: 44)
                VStack(alignment: .leading, spacing: .spacing1) {
                    Text(normalized.title)
                        .font(.omH4.weight(.bold))
                        .foregroundStyle(Color.fontPrimary)
                    Text(AppStrings.mindMapCounts(nodes: normalized.nodeCount, edges: normalized.edgeCount))
                        .font(.omSmall)
                        .foregroundStyle(Color.fontSecondary)
                }
            }

            if normalized.status == .invalidSource {
                invalidSourceView
            } else if let model = normalized.model {
                graphCanvas(model: model)
                zoomControls
                if normalized.status == .partial {
                    warningsView
                }
            }

            sourceView
        }
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
        let layout = NativeMindMapLayout(model: model, collapsedNodeIds: collapsedNodeIds)
        return GeometryReader { proxy in
            ZStack(alignment: .topLeading) {
                mindMapGrid
                ZStack(alignment: .topLeading) {
                    Canvas { context, _ in
                        var path = Path()
                        for edge in layout.edges {
                            path.move(to: CGPoint(x: edge.source.x + Constants.nodeWidth, y: edge.source.y + Constants.nodeHeight / 2))
                            path.addCurve(
                                to: CGPoint(x: edge.target.x, y: edge.target.y + Constants.nodeHeight / 2),
                                control1: CGPoint(x: edge.source.x + Constants.nodeWidth + 60, y: edge.source.y + Constants.nodeHeight / 2),
                                control2: CGPoint(x: edge.target.x - 60, y: edge.target.y + Constants.nodeHeight / 2)
                            )
                        }
                        context.stroke(path, with: .color(Color.grey30), lineWidth: 2)
                    }
                    .frame(width: layout.width, height: layout.height)

                    ForEach(layout.nodes) { node in
                        mindMapNode(node)
                            .position(x: node.x + Constants.nodeWidth / 2, y: node.y + Constants.nodeHeight / 2)
                    }
                }
                .frame(width: layout.width, height: layout.height, alignment: .topLeading)
                .scaleEffect(scale, anchor: .topLeading)
                .offset(pan)
            }
            .contentShape(Rectangle())
            .gesture(panGesture)
            .simultaneousGesture(zoomGesture)
            .onAppear {
                fit(layout: layout, viewport: proxy.size)
            }
            .onChange(of: collapsedNodeIds) { _, _ in
                fit(layout: NativeMindMapLayout(model: model, collapsedNodeIds: collapsedNodeIds), viewport: proxy.size)
            }
        }
        .frame(minHeight: 420)
        .clipShape(RoundedRectangle(cornerRadius: .radius8))
        .overlay(RoundedRectangle(cornerRadius: .radius8).stroke(Color.grey20, lineWidth: 1))
        .accessibilityIdentifier("mindmap-fullscreen-canvas")
    }

    private var mindMapGrid: some View {
        ZStack {
            Color.grey10
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
                context.fill(dots, with: .color(Color.grey30.opacity(0.65)))
            }
        }
    }

    private func mindMapNode(_ node: NativeMindMapViewNode) -> some View {
        VStack(alignment: .leading, spacing: .spacing1) {
            Text(node.label)
                .font(.omSmall.weight(.bold))
                .foregroundStyle(Color.fontPrimary)
                .lineLimit(2)
            if let description = node.description {
                Text(description)
                    .font(.omTiny)
                    .foregroundStyle(Color.fontSecondary)
                    .lineLimit(2)
            }
        }
        .padding(.leading, .spacing6)
        .padding(.trailing, node.hasChildren ? .spacing16 : .spacing6)
        .padding(.vertical, .spacing5)
        .frame(width: Constants.nodeWidth, minHeight: Constants.nodeHeight, alignment: .leading)
        .background(Color.grey0)
        .clipShape(RoundedRectangle(cornerRadius: .radius5))
        .overlay(RoundedRectangle(cornerRadius: .radius5).stroke(Color.grey20, lineWidth: 1))
        .shadow(color: .black.opacity(0.08), radius: 20, x: 0, y: 8)
        .overlay(alignment: .trailing) {
            if node.hasChildren {
                collapseButton(for: node)
                    .padding(.trailing, .spacing4)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(node.label)
    }

    private func collapseButton(for node: NativeMindMapViewNode) -> some View {
        Button {
            if collapsedNodeIds.contains(node.id) {
                collapsedNodeIds.remove(node.id)
            } else {
                collapsedNodeIds.insert(node.id)
            }
        } label: {
            Text(collapsedNodeIds.contains(node.id) ? "+" : "-")
                .font(.omSmall.weight(.bold))
                .foregroundStyle(Color.fontPrimary)
                .frame(width: 24, height: 24)
                .background(Color.grey10)
                .clipShape(Circle())
                .overlay(Circle().stroke(Color.grey20, lineWidth: 1))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(collapsedNodeIds.contains(node.id) ? AppStrings.mindMapExpand(node.label) : AppStrings.mindMapCollapse(node.label))
    }

    private var zoomControls: some View {
        HStack(spacing: .spacing3) {
            OMIconButton(icon: "minus", label: AppStrings.zoomOut, size: 34, iconSize: 16) {
                scale = max(Constants.minZoom, scale * 0.85)
                baseScale = scale
            }
            Text("\(Int((scale * 100).rounded()))%")
                .font(.omSmall.weight(.semibold))
                .foregroundStyle(Color.fontSecondary)
                .frame(minWidth: 52)
            OMIconButton(icon: "plus", label: AppStrings.zoomIn, size: 34, iconSize: 16) {
                scale = min(Constants.maxZoom, scale * 1.15)
                baseScale = scale
            }
            OMIconButton(icon: "restore", label: AppStrings.resetZoom, size: 34, iconSize: 16) {
                scale = 1
                baseScale = 1
                pan = .zero
                dragStartPan = .zero
            }
        }
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
        let nextScale = min(
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

private struct NativeMindMapNode: Identifiable {
    let id: String
    let label: String
    let description: String?
    let children: [String]
}

private struct NativeMindMapEdge {
    let source: String
    let target: String
}

private struct NativeMindMapDocument {
    let title: String
    let rootId: String
    let nodes: [NativeMindMapNode]
    let edges: [NativeMindMapEdge]
    let collapsedNodeIds: [String]
}

private struct NativeMindMapNormalization {
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

private enum NativeMindMapNormalizer {
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
            nodes.append(NativeMindMapNode(id: id, label: label ?? AppStrings.mindMapInvalidContent, description: cleanString(node["description"]), children: children))
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
            return NativeMindMapNode(id: node.id, label: node.label, description: node.description, children: filteredChildren)
        }

        let edges = normalizeEdges(raw["edges"], knownIds: knownIds, warnings: &warnings)
        let collapsed = ((raw["view"] as? [String: Any])?["collapsedNodeIds"] as? [Any])?.compactMap(cleanString) ?? []
        let model = NativeMindMapDocument(title: title, rootId: rootId, nodes: nodes, edges: edges, collapsedNodeIds: collapsed)
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
            edges.append(NativeMindMapEdge(source: source, target: target))
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

private struct NativeMindMapViewNode: Identifiable {
    let id: String
    let label: String
    let description: String?
    let x: CGFloat
    let y: CGFloat
    let hasChildren: Bool
}

private struct NativeMindMapViewEdge {
    let source: NativeMindMapViewNode
    let target: NativeMindMapViewNode
}

private struct NativeMindMapLayout {
    let nodes: [NativeMindMapViewNode]
    let edges: [NativeMindMapViewEdge]
    let width: CGFloat
    let height: CGFloat

    init(model: NativeMindMapDocument, collapsedNodeIds: Set<String>) {
        let nodesById = Dictionary(uniqueKeysWithValues: model.nodes.map { ($0.id, $0) })
        var visited = Set<String>()
        var viewNodes: [NativeMindMapViewNode] = []
        var nextRow: CGFloat = 0

        @discardableResult
        func visit(_ nodeId: String, depth: CGFloat) -> NativeMindMapViewNode? {
            guard let node = nodesById[nodeId], !visited.contains(nodeId) else { return nil }
            visited.insert(nodeId)
            let childIds = node.children.filter { nodesById[$0] != nil }
            var childViews: [NativeMindMapViewNode] = []
            if !collapsedNodeIds.contains(nodeId) {
                for childId in childIds {
                    if let child = visit(childId, depth: depth + 1) {
                        childViews.append(child)
                    }
                }
            }
            let row: CGFloat
            if childViews.isEmpty {
                row = nextRow
                nextRow += 1
            } else {
                row = childViews.reduce(0) { $0 + $1.y } / CGFloat(childViews.count) / MindMapEmbedRenderer.Constants.rowGap
            }
            let viewNode = NativeMindMapViewNode(
                id: node.id,
                label: node.label,
                description: node.description,
                x: depth * MindMapEmbedRenderer.Constants.columnGap,
                y: row * MindMapEmbedRenderer.Constants.rowGap,
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
