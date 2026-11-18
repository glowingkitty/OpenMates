// Tests of `SlidesPresentRemoteModel` (Features/Embeds/Renderers/SlidesPresentRemoteModel.swift):
// position text, Previous/Next/jump as remote-origin states with increasing seq,
// notes hidden by default and the not-presenting state after an ended or stale state.
// The core's encryption and ordering are covered by the crate tests; the core is faked here.
import Combine
import Foundation
import XCTest
@testable import OpenMates

@MainActor
private final class FakeSlidesRemoteClient: SlidesRemoteCoreClient {
    let subject = PassthroughSubject<SlidesRemoteFrame, Never>()
    var incoming: AnyPublisher<SlidesRemoteFrame, Never> { subject.eraseToAnyPublisher() }
    private(set) var sealed: [SlidesRemoteStateRecord] = []
    private(set) var sent: [String] = []
    private let orderings = SlidesRemoteOrderings()

    func encrypt(_ state: SlidesRemoteStateRecord) async throws -> String {
        sealed.append(state)
        return "cipher-\(sealed.count)"
    }
    func decrypt(embedId: String, ciphertext: String) async throws -> SlidesRemoteStateRecord {
        throw CoreError.Crypto
    }
    func send(embedId: String, ciphertext: String) async throws { sent.append(ciphertext) }
    func accept(_ state: SlidesRemoteStateRecord) -> Bool { orderings.accept(state: state) }
}

@MainActor
final class SlidesPresentRemoteTests: XCTestCase {
    private func slide(_ id: String, notes: String) -> SlideRecord {
        SlideRecord(id: id, transition: nil, notes: notes, elements: [])
    }

    private func make() -> (SlidesPresentRemoteModel, FakeSlidesRemoteClient) {
        let deck = SlideDeckRecord(
            title: "Deck", aspect: "16:9", width: 1920, height: 1080, template: "plain",
            slides: [slide("a", notes: "first"), slide("b", notes: "second"), slide("c", notes: "third")])
        let client = FakeSlidesRemoteClient()
        return (SlidesPresentRemoteModel(embedId: "deck", deck: deck, client: client), client)
    }

    private func presenter(seq: UInt64, index: UInt32 = 0, presenting: Bool = true) -> SlidesRemoteStateRecord {
        SlidesRemoteStateRecord(
            embedId: "deck", sessionId: "s1", seq: seq, index: index, step: 0, notesVisible: false,
            presenting: presenting, origin: .presenter)
    }

    // contract-test: supporting surface=gui.apple assertions=slides.present.remote-control
    func testPositionTextAndNotesHiddenByDefault() {
        let (model, _) = make()
        model.apply(presenter(seq: 1, index: 1))
        XCTAssertEqual(model.positionLabel, "2 / 3")
        XCTAssertFalse(model.notesVisible)
        XCTAssertEqual(model.notes, "second")
    }

    // contract-test: supporting surface=gui.apple assertions=slides.present.remote-control
    func testNextPreviousAndJumpSendIncreasingRemoteStates() async {
        let (model, client) = make()
        model.apply(presenter(seq: 5))
        await model.next()
        await model.next()
        await model.previous()
        await model.jump(toSlide: 3)
        XCTAssertEqual(client.sealed.map(\.seq), [6, 7, 8, 9])
        XCTAssertEqual(client.sealed.map(\.index), [1, 2, 1, 2])
        XCTAssertTrue(client.sealed.allSatisfy { $0.origin == .remote && $0.sessionId == "s1" })
        XCTAssertEqual(client.sent.count, 4)
        XCTAssertEqual(model.positionLabel, "3 / 3")
    }

    // contract-test: supporting surface=gui.apple assertions=slides.present.remote-relay-private
    func testNotesToggleIsLocalAndSendsNothing() {
        let (model, client) = make()
        model.apply(presenter(seq: 1))
        model.toggleNotes()
        XCTAssertTrue(model.notesVisible)
        XCTAssertTrue(client.sealed.isEmpty)
    }

    // contract-test: supporting surface=gui.apple assertions=slides.present.remote-control
    func testEndedAndStaleStatesShowNotPresenting() async {
        let (model, client) = make()
        let start = Date()
        model.apply(presenter(seq: 1), now: start)
        model.expireIfStale(now: start.addingTimeInterval(SlidesPresentRemoteModel.staleSeconds + 1))
        XCTAssertFalse(model.isPresenting)
        await model.next()
        XCTAssertTrue(client.sealed.isEmpty)
        model.apply(presenter(seq: 2), now: start)
        XCTAssertTrue(model.isPresenting)
        model.apply(presenter(seq: 3, presenting: false))
        XCTAssertFalse(model.isPresenting)
    }
}
