// Supporting native proof of the web MindMap layout algorithm.
// Web source: frontend/packages/ui/src/components/embeds/mindmaps/mindMapContent.ts
// Specification: specifications/features/chats/specification.yml
import XCTest
import SwiftUI
#if os(iOS)
import UIKit
#endif
@testable import OpenMates

@MainActor final class NativeMindMapLayoutTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testPreviewTitlePreservesExplicitTitleAndWebDefaultBeforeDocumentFallback() {
        let source = "{\"openmatesType\":\"mindmap\",\"schemaVersion\":1,\"title\":\"Document title\",\"rootId\":\"root\",\"nodes\":[{\"id\":\"root\",\"label\":\"Root\"}]}"
        XCTAssertEqual(NativeMindMapPreviewTitle.resolve(["source_json": AnyCodable(source), "title": AnyCodable("Preview title")]), "Preview title")
        XCTAssertEqual(NativeMindMapPreviewTitle.resolve(["source_json": AnyCodable(source)]), AppStrings.mindMap)
        XCTAssertEqual(NativeMindMapPreviewTitle.resolve(["source_json": AnyCodable(source), "title": AnyCodable("")]), "Document title")
        XCTAssertEqual(NativeMindMapPreviewTitle.resolve(["source_json": AnyCodable("{"), "title": AnyCodable("")]), AppStrings.mindMap)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testTopDownLevelsCenterParentsOverTheirChildren() throws {
        let layout = NativeMindMapLayout(model: document(), collapsedNodeIds: [])
        let nodes = Dictionary(uniqueKeysWithValues: layout.nodes.map { ($0.id, $0) })
        let root = try XCTUnwrap(nodes["root"])
        let branch = try XCTUnwrap(nodes["branch"])
        let left = try XCTUnwrap(nodes["left"])
        let right = try XCTUnwrap(nodes["right"])
        let peer = try XCTUnwrap(nodes["peer"])
        XCTAssertEqual(left.x, 0)
        XCTAssertEqual(right.x, 260)
        XCTAssertEqual(peer.x, 520)
        XCTAssertEqual(branch.x, (left.x + right.x) / 2)
        XCTAssertEqual(root.x, (branch.x + peer.x) / 2)
        XCTAssertEqual(root.y, 0)
        XCTAssertEqual(branch.y, 130)
        XCTAssertEqual(peer.y, 130)
        XCTAssertEqual(left.y, 260)
        XCTAssertEqual(layout.width, 740)
        XCTAssertEqual(layout.height, 324)
        XCTAssertEqual(layout.edges.count, 5, "Tree links and the explicit dependency must both render")
        XCTAssertEqual(branch.icon, "rocket")
        XCTAssertEqual(branch.color, "#123456")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testCollapsedDescendantsDoNotReturnAsDisconnectedRoots() {
        let model = document()
        let collapsed = NativeMindMapLayout(model: model, collapsedNodeIds: ["branch"])
        XCTAssertEqual(Set(collapsed.nodes.map(\.id)), ["root", "branch", "peer"])
        XCTAssertEqual(collapsed.edges.count, 2)
        XCTAssertEqual(collapsed.height, 194)
        let expanded = NativeMindMapLayout(model: model, collapsedNodeIds: [])
        XCTAssertEqual(Set(expanded.nodes.map(\.id)), Set(model.nodes.map(\.id)))
        let rootCollapsed = NativeMindMapLayout(model: model, collapsedNodeIds: ["root"])
        XCTAssertEqual(rootCollapsed.nodes.map(\.id), ["root"])
        XCTAssertEqual(rootCollapsed.width, 220)
        XCTAssertEqual(rootCollapsed.height, 64)
        XCTAssertTrue(rootCollapsed.edges.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testCyclesRemainBoundedAndIndependentNodesRemainVisible() {
        let model = NativeMindMapDocument(title: "Cycle", rootId: "a", nodes: [
            NativeMindMapNode(id: "a", label: "A", description: nil, children: ["b"]),
            NativeMindMapNode(id: "b", label: "B", description: nil, children: ["a"]),
            NativeMindMapNode(id: "independent", label: "Independent", description: nil, children: []),
        ], edges: [], collapsedNodeIds: [])
        let layout = NativeMindMapLayout(model: model, collapsedNodeIds: ["a"])
        XCTAssertEqual(Set(layout.nodes.map(\.id)), ["a", "independent"])
        XCTAssertEqual(layout.nodes.count, 2)
        XCTAssertTrue(layout.edges.isEmpty)
    }

    #if os(iOS) && DEBUG
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMountedRendererRefreshesNodesLabelsAndEdgesWhenContentIsReplaced() async throws {
        let source = MountedSource()
        let initial = expectation(description: "Initial graph mounted")
        let replacement = expectation(description: "Replacement graph selected in retained view")
        var replaced = false
        var initialSeen = false
        let host = UIHostingController(rootView: MountedRenderer(source: source) { layout in
            guard let layout else { return }
            if !initialSeen, layout.nodes.contains(where: { $0.label == "Before" }) {
                initialSeen = true
                initial.fulfill()
            } else if !replaced, layout.nodes.contains(where: { $0.label == "After" }) {
                replaced = true
                XCTAssertEqual(Set(layout.nodes.map(\.id)), ["root", "new-child"])
                XCTAssertEqual(layout.edges.count, 1)
                XCTAssertEqual(layout.height, 194)
                replacement.fulfill()
            }
        })
        let window = UIWindow(frame: CGRect(x: 0, y: 0, width: 402, height: 700))
        window.rootViewController = host
        window.makeKeyAndVisible()
        defer { window.isHidden = true; window.rootViewController = nil }
        await fulfillment(of: [initial], timeout: 5)
        source.data = MountedSource.payload(label: "After", child: "new-child")
        await fulfillment(of: [replacement], timeout: 5)
    }

    @MainActor private final class MountedSource: ObservableObject {
        @Published var data = payload(label: "Before", child: nil)
        static func payload(label: String, child: String?) -> [String: AnyCodable] {
            var nodes: [[String: Any]] = [["id": "root", "label": label, "children": child.map { [$0] } ?? []]]
            if let child { nodes.append(["id": child, "label": "Added child"]) }
            return ["model": AnyCodable(["openmatesType": "mindmap", "schemaVersion": 1,
                                        "rootId": "root", "nodes": nodes])]
        }
    }
    private struct MountedRenderer: View {
        @ObservedObject var source: MountedSource
        let observed: (NativeMindMapLayout?) -> Void
        var body: some View {
            MindMapEmbedRenderer(data: source.data, mode: .fullscreen)
                .onPreferenceChange(NativeMindMapRenderedLayoutKey.self, perform: observed)
        }
    }
    #endif

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testDownloadNormalizesCanonicalJSONAndPreservesEdgeAndViewMetadata() throws {
        let model: [String: Any] = ["openmatesType": "mindmap", "schemaVersion": 1,
            "title": "Canonical", "rootId": "missing", "privateExtra": "discard",
            "nodes": [["id": "root", "label": "Root", "children": ["child", "missing"], "icon": "rocket", "color": "#123456"],
                      ["id": "child", "label": "Child"], ["id": "child", "label": "Duplicate"]],
            "edges": [["source": "root", "target": "child", "type": "dependency", "label": "Before launch", "extra": true],
                      ["source": "missing", "target": "child"]],
            "view": ["layout": "radial-tree", "collapsedNodeIds": ["root"]]]
        let file = NativeMindMapDownloadFile.build(data: ["model": AnyCodable(model), "title": AnyCodable("  Launch Plan / 2026!  ")])
        XCTAssertEqual(file.filename, "launch-plan-2026.ommindmap")
        XCTAssertEqual(file.mimeType, "application/json")
        XCTAssertTrue(file.content.hasSuffix("\n"))
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(file.content.utf8)) as? [String: Any])
        XCTAssertEqual(json["openmatesType"] as? String, "mindmap")
        XCTAssertEqual(json["schemaVersion"] as? Int, 1)
        XCTAssertEqual(json["rootId"] as? String, "root")
        XCTAssertEqual(json["title"] as? String, "Canonical", "Header title affects the filename, not canonical document title")
        XCTAssertNil(json["privateExtra"])
        let nodes = try XCTUnwrap(json["nodes"] as? [[String: Any]])
        XCTAssertEqual(nodes.count, 2)
        XCTAssertEqual(nodes[0]["children"] as? [String], ["child"])
        XCTAssertEqual(nodes[0]["icon"] as? String, "rocket")
        XCTAssertEqual(nodes[0]["color"] as? String, "#123456")
        let edges = try XCTUnwrap(json["edges"] as? [[String: Any]])
        XCTAssertEqual(edges.count, 1)
        XCTAssertEqual(edges[0]["type"] as? String, "dependency")
        XCTAssertEqual(edges[0]["label"] as? String, "Before launch")
        XCTAssertNil(edges[0]["extra"])
        XCTAssertEqual((json["view"] as? [String: Any])?["collapsedNodeIds"] as? [String], ["root"])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testInvalidSourceCanStillDownloadWithFallbackFilename() {
        let source = "This is not a valid mindmap document"
        let file = NativeMindMapDownloadFile.build(data: ["source_json": AnyCodable(source), "title": AnyCodable("🧠")])
        XCTAssertEqual(file.filename, "mindmap.ommindmap")
        XCTAssertEqual(file.content, source)
    }

    private func document() -> NativeMindMapDocument {
        NativeMindMapDocument(title: "Plan", rootId: "root", nodes: [
            NativeMindMapNode(id: "root", label: "Root", description: nil, children: ["branch", "peer"]),
            NativeMindMapNode(id: "branch", label: "Branch", description: nil, icon: "rocket", color: "#123456", children: ["left", "right"]),
            NativeMindMapNode(id: "left", label: "Left", description: nil, children: []),
            NativeMindMapNode(id: "right", label: "Right", description: nil, children: []),
            NativeMindMapNode(id: "peer", label: "Peer", description: nil, children: []),
        ], edges: [NativeMindMapEdge(source: "left", target: "peer")], collapsedNodeIds: [])
    }
}
