import XCTest
@testable import OpenMates

@MainActor
final class NativePCBSchematicActionTests: XCTestCase {
    private let success = Data(#"{"compile_id":"compile-public","status":"succeeded","logs":"Public logs","artifact_manifest":{"files":[{"id":"board-public","name":"../../board.kicad_pcb","type":"kicad"}]}}"#.utf8)

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.persistence.client-encrypted
    func testPreparePostsOnlyIDAndForceThenDownloadsActualArtifactBytes() async throws {
        let state = NativePCBSchematicActions()
        state.initialize(["code": .init("private source must never be uploaded")])
        var requests: [(String, String, Data?)] = []
        let transport = NativePCBTransport(request: { method, path, body in
            requests.append((method.rawValue, path, body))
            return path.contains("/artifacts/") ? Data([0, 1, 255, 42]) : self.success
        }, validate: {})
        await state.prepare(embedID: "embed-public", transport: transport)
        XCTAssertEqual(state.status, "succeeded")
        XCTAssertFalse(state.preparing)
        XCTAssertFalse(state.showLogs)
        XCTAssertEqual(state.logs, "Public logs")
        XCTAssertEqual(requests[0].0, "POST")
        XCTAssertEqual(requests[0].1, "/v1/electronics/pcb-schematic/embeds/embed-public/prepare-files")
        XCTAssertEqual(requests[0].2, Data(#"{"force":false}"#.utf8))
        let artifact = try XCTUnwrap(state.artifacts.first)
        let exported = try await state.download(artifact, transport: transport)
        XCTAssertEqual(exported.bytes, Data([0, 1, 255, 42]))
        XCTAssertFalse(exported.filename.contains("/"))
        XCTAssertEqual(requests[1].0, "GET")
        XCTAssertEqual(requests[1].1, "/v1/electronics/pcb-schematic/compile/compile-public/artifacts/board-public")
        XCTAssertNil(requests[1].2)
        try await state.refresh(transport: transport)
        XCTAssertEqual(requests[2].1, "/v1/electronics/pcb-schematic/compile/compile-public")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testSelectionCancellationDiscardsLateCompileAndDownloadResults() async throws {
        let state = NativePCBSchematicActions()
        await state.prepare(embedID: "public", transport: .init(request: { _, _, _ in
            state.cancel(); return self.success
        }, validate: {}))
        XCTAssertNil(state.compileID)
        XCTAssertTrue(state.artifacts.isEmpty)
        state.initialize(nil)
        await state.prepare(embedID: "public", transport: .init(request: { _, _, _ in self.success }, validate: {}))
        let artifact = try XCTUnwrap(state.artifacts.first)
        do {
            _ = try await state.download(artifact, transport: .init(request: { _, _, _ in
                state.cancel(); return Data("late bytes".utf8)
            }, validate: {}))
            XCTFail("A stale selection must never export bytes")
        } catch is CancellationError { }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testBoundaryValidationBlocksDispatchAndLateStateApplication() async {
        let state = NativePCBSchematicActions()
        var requests = 0
        await state.prepare(embedID: "public", transport: .init(request: { _, _, _ in
            requests += 1; return self.success
        }, validate: { throw CancellationError() }))
        XCTAssertEqual(requests, 0)
        state.initialize(nil)
        var valid = true
        await state.prepare(embedID: "public", transport: .init(request: { _, _, _ in
            valid = false; requests += 1; return self.success
        }, validate: { if !valid { throw CancellationError() } }))
        XCTAssertEqual(requests, 1)
        XCTAssertNil(state.compileID)
        XCTAssertTrue(state.artifacts.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testFailureLogsHiddenInitiallyAndInitializeResetsSelection() async {
        let state = NativePCBSchematicActions()
        await state.prepare(embedID: "public", transport: .init(request: { _, _, _ in
            Data(#"{"compile_id":"compile-public","status":"failed","error":"Public error","logs":"Public failure logs"}"#.utf8)
        }, validate: {}))
        XCTAssertEqual(state.status, "failed")
        XCTAssertEqual(state.error, "Public error")
        XCTAssertEqual(state.logs, "Public failure logs")
        XCTAssertFalse(state.showLogs)
        state.showLogs = true
        state.initialize(nil)
        XCTAssertFalse(state.showLogs)
        XCTAssertNil(state.error)
        XCTAssertEqual(state.status, "idle")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testMalformedIDsCannotCrossOwnerAuthorizedRoutes() {
        for id in ["", ".", "..", "other/prepare-files", "other?force=true", "other%2Fboard", "other#secret"] {
            XCTAssertThrowsError(try NativePCBSchematicActions.segment(id))
        }
        XCTAssertEqual(try NativePCBSchematicActions.segment("public-board_v1.2"), "public-board_v1.2")
    }
}
