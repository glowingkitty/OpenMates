// Calendar and fullscreen download contracts without network/calendar writes.
import XCTest
import ZIPFoundation
import ImageIO
#if os(iOS)
import EventKit
#endif
@testable import OpenMates

@MainActor
final class NativeEmbedActionTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testEventAndFitnessCalendarPreserveWebDatesLocationAndSource() throws {
        let zone = try XCTUnwrap(TimeZone(identifier: "Europe/Berlin"))
        let event = try XCTUnwrap(EventEmbedCalendarFile.make([
            "title": .init("Public conference"), "date_start": .init("2026-10-04"), "date_end": .init("2026-10-06"),
            "venue": .init(["name": "Public venue", "address": "Public street", "city": "Berlin"]),
            "organizer": .init(["name": "Public organizer"]), "url": .init("https://example.invalid/event")
        ], timeZone: zone))
        XCTAssertTrue(event.content.contains("DTSTART;VALUE=DATE:20261004"))
        XCTAssertTrue(event.content.contains("DTEND;VALUE=DATE:20261006"))
        XCTAssertTrue(event.content.contains("Organizer: Public organizer"))
        XCTAssertEqual(event.event?.sourceURL?.absoluteString, "https://example.invalid/event")
        XCTAssertTrue(event.event?.allDay == true)
        let fitness = try XCTUnwrap(FitnessEmbedCalendarFile.make([
            "name": .init("Yoga"), "date": .init("2026-10-04"), "time_range": .init("09:30 - 10:45"),
            "venue_name": .init("Public gym"), "address": .init("Public address"),
            "plans_required": .init("M|L"), "detail_url": .init("https://example.invalid/class")
        ], timeZone: zone))
        XCTAssertTrue(fitness.content.contains("DTSTART:20261004T073000Z"))
        XCTAssertTrue(fitness.content.contains("DTEND:20261004T084500Z"))
        XCTAssertEqual(fitness.event?.location, "Public gym, Public address")
        XCTAssertTrue(fitness.event?.notes?.contains("Plans: M, L") == true)
    }

    #if os(iOS)
    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testSystemEditorEventPreservesAllDayCivilDatesAndTimedOffsetWithoutSaving() throws {
        let zone = try XCTUnwrap(TimeZone(identifier: "America/Los_Angeles"))
        let file = try XCTUnwrap(EmbedCalendarFile.build(title: "Public all-day event", start: "2026-10-04",
            location: "Public venue", description: "Public notes", url: "https://example.invalid/event", timeZone: zone))
        let store = EKEventStore()
        let event = NativeEmbedActionController.makeEvent(try XCTUnwrap(file.event), store: store)
        var calendar = Calendar(identifier: .gregorian); calendar.timeZone = zone
        XCTAssertEqual(calendar.component(.day, from: event.startDate), 4)
        XCTAssertEqual(calendar.component(.day, from: event.endDate), 5)
        XCTAssertEqual(calendar.component(.hour, from: event.startDate), 0)
        XCTAssertTrue(event.isAllDay)
        XCTAssertEqual(event.title, "Public all-day event")
        XCTAssertEqual(event.location, "Public venue")
        XCTAssertEqual(event.notes, "Public notes")
        XCTAssertEqual(event.url, URL(string: "https://example.invalid/event"))
        let timed = try XCTUnwrap(EmbedCalendarFile.build(title: "Timed", start: "2026-10-04T09:30:00+02:00", location: nil,
            description: nil, url: nil, timeZone: zone))
        let timedEvent = NativeEmbedActionController.makeEvent(try XCTUnwrap(timed.event), store: store)
        XCTAssertFalse(timedEvent.isAllDay)
        XCTAssertEqual(timedEvent.endDate.timeIntervalSince(timedEvent.startDate), 3600)
        XCTAssertEqual(timedEvent.startDate, ISO8601DateFormatter().date(from: "2026-10-04T07:30:00Z"))
    }
    #endif

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testFileDownloadFetchesActualBytesWithSafeNameAndMIME() async throws {
        let embed = record("file-file", ["filename": "../../public.txt", "mime_type": "text/plain",
            "download_url": "https://example.invalid/download?token=public-fixture", "download_expires_at": 0])
        let source = try XCTUnwrap(NativeEmbedDownload.source(embed))
        let expected = Data("Actual public file bytes".utf8)
        let file = try await source.load(scope: nil, recipient: nil, fetch: { url in
            XCTAssertEqual(url.path, "/download")
            return expected
        })
        XCTAssertEqual(file.bytes, expected)
        XCTAssertEqual(file.filename, "public.txt")
        XCTAssertEqual(file.mimeType, "text/plain")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testPrivateDOCXUsesNoncePrefixedDecryptionAndNeverFallsBackToPlainURL() async throws {
        let embed = record("docs-doc", ["filename": "public.docx", "docx_s3_key": "public-fixture-docx-key", "aes_key": "fixture-aes-key"])
        let source = try XCTUnwrap(NativeEmbedDownload.source(embed))
        let bytes = Data([0x50, 0x4b, 0x03, 0x04])
        let file = try await source.load(scope: "disposable-test-scope", recipient: nil,
            fetch: { _ in XCTFail("Private artifacts cannot download plaintext URLs"); return Data() },
            decrypt: { s3, key, nonce, marker in
                XCTAssertEqual(s3, "public-fixture-docx-key")
                XCTAssertEqual(key, "fixture-aes-key")
                XCTAssertNil(nonce)
                XCTAssertEqual(marker, S3MediaClient.noncePrefixedEncryption)
                return bytes
            })
        XCTAssertEqual(file.bytes, bytes)
        XCTAssertEqual(file.mimeType, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        XCTAssertNil(NativeEmbedDownload.source(record("audio-recording", ["aes_key": "fixture-key", "audio_url": "https://example.invalid/plain.mp3"])))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testNotebookAndApplicationZIPContainRealSourcesAndRejectMissingChildren() throws {
        let notebook = record("code-notebook", ["filename": "public.ipynb", "notebook": ["nbformat": 4, "cells": [["cell_type": "code", "source": ["print('public')"]]]]])
        guard case .inline(let ipynb) = try XCTUnwrap(NativeEmbedDownload.source(notebook)) else { return XCTFail("Expected notebook export") }
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: ipynb.bytes) as? [String: Any])
        XCTAssertEqual(object["nbformat"] as? Int, 4)
        let child = record("code-code", ["code": "print('public')", "language": "python", "filename": "main.py"], id: "public-child")
        let refs: [[String: Any]] = [["embed_id": child.id, "path": "../src/main.py"]]
        let zip = try NativeEmbedDownload.applicationZIP(refs: refs, records: [child.id: child], renderText: { $0 })
        let archive = try Archive(data: zip, accessMode: .read)
        let entry = try XCTUnwrap(archive["src/main.py"])
        var exportedSource = Data()
        _ = try archive.extract(entry) { exportedSource.append($0) }
        XCTAssertEqual(String(data: exportedSource, encoding: .utf8), "print('public')")
        XCTAssertThrowsError(try NativeEmbedDownload.applicationZIP(refs: refs, records: [:], renderText: { $0 }))
        let wrongType = record("file-file", ["code": "must not be exported as code"], id: child.id)
        XCTAssertThrowsError(try NativeEmbedDownload.applicationZIP(refs: refs, records: [child.id: wrongType], renderText: { $0 }))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testCancellationAndContextFencesRejectStaleDownloadsAndUnsafeExternalURLs() async throws {
        let generation = UUID(), selection = UUID()
        let fence = NativeEmbedActionFence(accountGeneration: generation, selectionGeneration: selection)
        XCTAssertTrue(fence.permits(account: generation, selection: selection))
        XCTAssertFalse(fence.permits(account: UUID(), selection: selection))
        XCTAssertFalse(fence.permits(account: generation, selection: UUID()))
        let source = NativeEmbedDownload.Source.remote(filename: "public.txt", mime: "text/plain", url: URL(string: "https://example.invalid")!)
        do {
            _ = try await source.load(scope: nil, recipient: nil, fetch: { _ in throw CancellationError() })
            XCTFail("Cancellation must not create an export")
        } catch is CancellationError { }
        for url in ["javascript:alert(1)", "file:///private/data", "https://owner:secret@example.invalid", "data:text/plain,private"] {
            XCTAssertNil(NativeEmbedActionURL.external(url))
        }
        XCTAssertNotNil(NativeEmbedActionURL.external("https://example.invalid/article"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted
    func testExportFenceRejectsTeamSwitchAndSwitchBackWithinSameAccountAndSelection() {
        let account = UUID(), selection = UUID()
        let fence = NativeEmbedActionFence(accountGeneration: account, selectionGeneration: selection, teamEpoch: 7, teamID: "synthetic-team-a")
        XCTAssertTrue(fence.permits(account: account, selection: selection, teamEpoch: 7, teamID: "synthetic-team-a"))
        XCTAssertFalse(fence.permits(account: account, selection: selection, teamEpoch: 8, teamID: "synthetic-team-b"))
        XCTAssertFalse(fence.permits(account: account, selection: selection, teamEpoch: 9, teamID: "synthetic-team-a"))
        XCTAssertFalse(fence.permits(account: account, selection: selection, teamEpoch: 7, teamID: nil))
        XCTAssertFalse(fence.permits(account: account, selection: selection, teamEpoch: 7, teamID: "synthetic-team-b"))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.persistence.client-encrypted,chats.surface.semantic-parity
    func testOldOSCompletionCannotReleaseNewPresentationOrTemporaryDirectory() {
        let oldController = NSObject(), nextController = NSObject()
        let oldDirectory = URL(fileURLWithPath: "/synthetic/old-export"), nextDirectory = URL(fileURLWithPath: "/synthetic/next-export")
        let lease = NativeEmbedPresentationLease(controller: oldController, directory: oldDirectory)
        XCTAssertTrue(lease.permits(controller: oldController, directory: oldDirectory))
        XCTAssertFalse(lease.permits(controller: nextController, directory: nextDirectory))
        XCTAssertFalse(lease.permits(controller: oldController, directory: nextDirectory))
        XCTAssertFalse(lease.permits(controller: nextController, directory: oldDirectory))
        XCTAssertFalse(lease.permits(controller: nil, directory: nil))
        // Calendar editors and save panels have no temporary file directory;
        // their controller identity still isolates delayed completion callbacks.
        let calendarLease = NativeEmbedPresentationLease(controller: oldController, directory: nil)
        XCTAssertTrue(calendarLease.permits(controller: oldController, directory: nil))
        XCTAssertFalse(calendarLease.permits(controller: nextController, directory: nil))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.persistence.client-encrypted
    func testLegacyDOCXIsRealOpenXMLPackageWithSanitizedHTML() throws {
        let bytes = try NativeDocumentDOCX.build(html: "<h1>Public document</h1><p>Actual paragraph</p><script>privateUpload()</script><img src='https://example.invalid/private'>")
        let archive = try Archive(data: bytes, accessMode: .read)
        for path in ["[Content_Types].xml", "_rels/.rels", "word/document.xml", "word/_rels/document.xml.rels", "word/afchunk.mht"] {
            XCTAssertNotNil(archive[path])
        }
        let chunk = try extract("word/afchunk.mht", archive: archive)
        let encoded = try XCTUnwrap(String(data: chunk, encoding: .utf8)?.components(separatedBy: "\r\n\r\n").last?.components(separatedBy: "\r\n--openmates-docx--").first)
        let decoded = try XCTUnwrap(Data(base64Encoded: encoded, options: .ignoreUnknownCharacters))
        let text = try XCTUnwrap(String(data: decoded, encoding: .utf8))
        XCTAssertTrue(text.contains("Public document")); XCTAssertTrue(text.contains("Actual paragraph"))
        XCTAssertFalse(text.contains("privateUpload")); XCTAssertFalse(text.contains("https://example.invalid/private"))
        guard case .inline(let file) = try XCTUnwrap(NativeEmbedDownload.source(record("docs-doc", ["filename": "public.docx", "html": "<p>Actual public paragraph</p>"]))) else { return XCTFail("Expected local DOCX package") }
        XCTAssertEqual(file.filename, "public.docx")
        XCTAssertNotNil(try Archive(data: file.bytes, accessMode: .read)["word/document.xml"])
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testMultipleTranscriptAndDiagramExportsPreserveAllActualContent() throws {
        let transcripts = record("app:videos:get_transcript", ["results": [
            ["title": "First public video", "transcript": "First actual transcript", "word_count": 3, "url": "https://example.invalid/first"],
            ["title": "Second public video", "transcript": "Second actual transcript", "word_count": 4, "url": "https://example.invalid/second"]
        ]])
        let text = try XCTUnwrap(NativeEmbedDownload.copyText(transcripts))
        XCTAssertTrue(text.contains("First actual transcript")); XCTAssertTrue(text.contains("Second actual transcript"))
        XCTAssertTrue(text.contains("\n\n---\n\n")); XCTAssertTrue(text.contains("Word count: 4"))
        let diagram = record("diagrams-mermaid", ["source": "graph TD; Public-->Fixture"])
        guard case .inline(let file) = try XCTUnwrap(NativeEmbedDownload.source(diagram)) else { return XCTFail("Expected diagram source") }
        XCTAssertEqual(file.bytes, Data("graph TD; Public-->Fixture".utf8)); XCTAssertTrue(file.filename.hasSuffix(".mmd"))
        XCTAssertNil(NativeEmbedDownload.copyText(record("app:images:generate", ["aes_key": "private-key", "s3_key": "private-key-ref"])))
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity,chats.persistence.client-encrypted
    func testDesignExportsUseRealValidatedSVGColorAndPaletteWithoutNetwork() async throws {
        let svg = Data("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><path fill='currentColor' d='M0 0h16v16H0z'/></svg>".utf8)
        let base = URL(string: "https://api.example.invalid/")!
        XCTAssertEqual(NativeDesignIconActions.url("/v1/icons/public.svg", apiBase: base)?.host, "api.example.invalid")
        XCTAssertNil(NativeDesignIconActions.url("javascript:alert(1)", apiBase: base))
        let loaded = try await NativeDesignIconActions.load(base, recipient: nil, fetch: { _ in svg })
        let source = try NativeDesignIconActions.prepare(loaded, color: "#123456", palette: false)
        XCTAssertTrue(String(data: source.data, encoding: .utf8)!.contains("#123456"))
        XCTAssertEqual(try NativeDesignIconActions.prepare(svg, color: "#123456", palette: true).data, svg)
        XCTAssertThrowsError(try NativeDesignIconActions.prepare(svg, color: "url(https://example.invalid/private)", palette: false))
        XCTAssertThrowsError(try NativeDesignIconActions.prepare(Data("<svg><script>upload()</script></svg>".utf8), color: "#123456", palette: false))
        do { _ = try await NativeDesignIconActions.png(source, size: 4097); XCTFail("Unbounded exports must fail") }
        catch { }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testPNGExportHasRequestedPixelDimensionsAndActualIconPixels() async throws {
        let source = try XCTUnwrap(StaticSVGImageSource(data: Data("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><path fill='#123456' d='M0 0h16v16H0z'/></svg>".utf8)))
        let bytes = try await NativeDesignIconActions.png(source, size: 32)
        XCTAssertEqual(Array(bytes.prefix(8)), [137, 80, 78, 71, 13, 10, 26, 10])
        let decoder = try XCTUnwrap(CGImageSourceCreateWithData(bytes as CFData, nil))
        let image = try XCTUnwrap(CGImageSourceCreateImageAtIndex(decoder, 0, nil))
        XCTAssertEqual(image.width, 32); XCTAssertEqual(image.height, 32)
        let pixel = UnsafeMutablePointer<UInt8>.allocate(capacity: 4); defer { pixel.deallocate() }
        let context = try XCTUnwrap(CGContext(data: pixel, width: 1, height: 1, bitsPerComponent: 8, bytesPerRow: 4,
            space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue))
        context.draw(image, in: CGRect(x: 0, y: 0, width: 1, height: 1))
        XCTAssertGreaterThan(pixel[3], 240, "PNG cannot be an empty/transparent placeholder")
        XCTAssertEqual(Double(pixel[0]), 18, accuracy: 2); XCTAssertEqual(Double(pixel[1]), 52, accuracy: 2); XCTAssertEqual(Double(pixel[2]), 86, accuracy: 2)
    }

    private func extract(_ path: String, archive: Archive) throws -> Data {
        let entry = try XCTUnwrap(archive[path]); var bytes = Data()
        _ = try archive.extract(entry) { bytes.append($0) }
        return bytes
    }

    private func record(_ type: String, _ data: [String: Any], id: String = "public-fixture") -> EmbedRecord {
        EmbedRecord(id: id, type: type, status: .finished, data: .raw(data.mapValues { AnyCodable($0) }),
            parentEmbedId: nil, appId: nil, skillId: nil, embedIds: nil, createdAt: nil)
    }
}
