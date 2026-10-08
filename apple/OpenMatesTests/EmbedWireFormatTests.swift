import XCTest
import SwiftUI
#if os(iOS)
import UIKit
#endif
@testable import OpenMates

final class EmbedWireFormatTests: XCTestCase {
    #if os(iOS)
    // contract-test: supporting surface=gui.apple assertions=code-run.surface-parity
    func testCodeFilenameNullAndBlankMetadataPreservesLanguageAndRealNames() throws {
        for absent in [AnyCodable(NSNull()), AnyCodable("null"), AnyCodable(" NULL "), AnyCodable("  ")] {
            let content = AppleCodeEmbedContent(data: ["filename": absent, "language": AnyCodable("markdown"), "code": AnyCodable("# Notes")])
            XCTAssertNil(content.filename)
            XCTAssertNil(content.previewFilename)
            XCTAssertEqual(content.language, "markdown")
        }
        let decoded = try JSONDecoder().decode([String: AnyCodable].self,
            from: Data(##"{"filename":null,"language":"markdown","code":"# Notes"}"##.utf8))
        XCTAssertNil(AppleCodeEmbedContent(data: decoded).filename)
        let aliased = AppleCodeEmbedContent(data: ["filename": AnyCodable("null"), "path": AnyCodable("docs/notes.md"), "language": AnyCodable("markdown")])
        XCTAssertEqual(aliased.previewFilename, "notes.md")
        let missing = AppleCodeEmbedContent(data: ["language": AnyCodable("markdown"), "code": AnyCodable("# Notes")])
        XCTAssertNil(missing.filename)
        XCTAssertEqual(missing.language, "markdown")
        let real = AppleCodeEmbedContent(data: ["filename": AnyCodable("  C:\\docs\\null.md  "), "language": AnyCodable("markdown"), "code": AnyCodable("# Notes")])
        XCTAssertEqual(real.filename, "C:\\docs\\null.md")
        XCTAssertEqual(real.previewFilename, "null.md")
        let parsed = AppleCodeEmbedContent.parse("markdown:notes.md\n# Notes", language: "markdown", filename: "null")
        XCTAssertEqual(parsed.filename, "notes.md")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    @MainActor
    func testProductionSheetFullscreenBoundsLargeTableAndOwnsStickyScrolling() async throws {
        let rows = (0..<1_000).map { "| Row \($0) | Synthetic note \($0) |" }.joined(separator: "\n")
        let embed = EmbedRecord(id: "bounded-sheet", type: EmbedType.sheetsSheet.rawValue, status: .finished,
                                data: .raw(["table": AnyCodable("| Name | Note |\n| --- | --- |\n" + rows)]),
                                parentEmbedId: nil, appId: "sheets", skillId: "sheet", embedIds: nil, createdAt: nil)
        let host = UIHostingController(rootView: EmbedFullscreenContainer(
            embeds: [embed], initialEmbedId: embed.id, allEmbedRecords: [embed.id: embed], chatId: nil,
            isSidePanel: true))
        let scene = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first
        let previousKeyWindow = scene?.windows.first { $0.isKeyWindow }
        let hostWindow = scene.map { UIWindow(windowScene: $0) }
            ?? UIWindow(frame: CGRect(x: 0, y: 0, width: 402, height: 874))
        hostWindow.rootViewController = host
        hostWindow.makeKeyAndVisible()
        defer {
            hostWindow.isHidden = true
            hostWindow.rootViewController = nil
            previousKeyWindow?.makeKeyAndVisible()
        }
        func descendants(of view: UIView) -> [UIView] {
            view.subviews.flatMap { [$0] + descendants(of: $0) }
        }
        func table() -> UICollectionView? {
            descendants(of: host.view).compactMap { $0 as? UICollectionView }
                .first { $0.accessibilityIdentifier == "sheet-fullscreen-table" }
        }
        let mounted = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            MainActor.assumeIsolated {
                host.view.layoutIfNeeded()
                guard let collection = table() else { return false }
                collection.layoutIfNeeded()
                return collection.bounds.height > 0 && collection.bounds.height < host.view.bounds.height
                    && !collection.visibleCells.isEmpty
            }
        }, object: nil)
        let mountedResult = await XCTWaiter.fulfillment(of: [mounted], timeout: 5)
        XCTAssertEqual(mountedResult, .completed, "The production container must give the table a finite viewport")
        let collection = try XCTUnwrap(table())
        XCTAssertGreaterThan(collection.contentSize.height, collection.bounds.height * 10)
        XCTAssertLessThan(collection.visibleCells.count, collection.numberOfItems(inSection: 0) / 10,
                          "A large fullscreen table must mount only the visible cells")
        let layout = try XCTUnwrap(collection.collectionViewLayout as? SheetFullscreenCollectionLayout)
        let target = try XCTUnwrap(layout.layoutAttributesForItem(at: IndexPath(item: 302 * 3 + 1, section: 0)))
        collection.setContentOffset(CGPoint(x: 0, y: target.frame.minY), animated: false)
        let scrolled = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            MainActor.assumeIsolated {
                collection.layoutIfNeeded()
                return collection.visibleCells.flatMap { descendants(of: $0) }.compactMap { $0 as? UITextView }
                    .contains { $0.text == "Row 300" }
            }
        }, object: nil)
        let scrolledResult = await XCTWaiter.fulfillment(of: [scrolled], timeout: 5)
        XCTAssertEqual(scrolledResult, .completed, "The table must scroll its own rows")
        let letter = try XCTUnwrap(layout.layoutAttributesForItem(at: IndexPath(item: 1, section: 0)))
        let header = try XCTUnwrap(layout.layoutAttributesForItem(at: IndexPath(item: 4, section: 0)))
        XCTAssertEqual(letter.frame.minY, collection.bounds.minY, accuracy: 0.01)
        XCTAssertEqual(header.frame.minY, letter.frame.maxY, accuracy: 0.01)
        XCTAssertTrue(collection.visibleCells.contains { $0.accessibilityIdentifier == "sheet-sort-column-0" })
        XCTAssertLessThan(collection.visibleCells.count, collection.numberOfItems(inSection: 0) / 10)
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    @MainActor
    func testSheetWrappedRowsResizeAndHeadersStayPinnedAcrossViewportMetrics() throws {
        let layout = SheetFullscreenCollectionLayout()
        let collection = UICollectionView(frame: CGRect(x: 0, y: 0, width: 200, height: 160), collectionViewLayout: layout)
        collection.contentInset.top = 70
        collection.bounds.origin.y = -70
        let longValue = String(repeating: "Wrapped cell content ", count: 12)
        let rows = [["Ada", "Short"], ["Zoe", longValue]] + Array(repeating: ["More", "Rows"], count: 100)
        layout.configure(headers: ["Name", "Note"], rows: rows, widths: [80, 80], viewportWidth: 402)
        layout.prepare()
        let shortRow = try XCTUnwrap(layout.layoutAttributesForItem(at: IndexPath(item: 7, section: 0)))
        let wrappedRow = try XCTUnwrap(layout.layoutAttributesForItem(at: IndexPath(item: 10, section: 0)))
        XCTAssertGreaterThan(wrappedRow.frame.height, shortRow.frame.height * 2, "Long content must expand its entire row instead of ellipsizing")
        let mobileGutter = try XCTUnwrap(layout.layoutAttributesForItem(at: IndexPath(item: 0, section: 0)))
        XCTAssertEqual(mobileGutter.frame.width, 49)
        XCTAssertEqual(layout.metrics.font.pointSize, 12)
        XCTAssertEqual(layout.metrics.horizontalPadding, 8)

        let initialLetter = try XCTUnwrap(layout.layoutAttributesForItem(at: IndexPath(item: 1, section: 0)))
        XCTAssertEqual(initialLetter.frame.minY, 0, "A caller inset affects the initial viewport, not sticky anchoring")

        collection.bounds.origin = CGPoint(x: 50, y: 100)
        layout.prepare()
        let letter = try XCTUnwrap(layout.layoutAttributesForItem(at: IndexPath(item: 1, section: 0)))
        let header = try XCTUnwrap(layout.layoutAttributesForItem(at: IndexPath(item: 4, section: 0)))
        let corner = try XCTUnwrap(layout.layoutAttributesForItem(at: IndexPath(item: 0, section: 0)))
        XCTAssertEqual(letter.frame.minY, collection.bounds.minY)
        XCTAssertEqual(header.frame.minY, letter.frame.maxY)
        XCTAssertEqual(corner.frame.minX, collection.bounds.minX + collection.adjustedContentInset.left)
        let visible = try XCTUnwrap(layout.layoutAttributesForElements(in: collection.bounds))
        XCTAssertTrue(visible.contains { $0.indexPath.item == 0 }, "The sticky corner must survive visible-range culling")
        XCTAssertLessThan(visible.count, rows.count, "Wrapping must preserve collection virtualization")

        layout.configure(headers: ["Name", "Note"], rows: rows, widths: [80, 80], viewportWidth: 1194)
        layout.prepare()
        let desktopGutter = try XCTUnwrap(layout.layoutAttributesForItem(at: IndexPath(item: 0, section: 0)))
        XCTAssertEqual(desktopGutter.frame.width, 65)
        XCTAssertEqual(layout.metrics.font.pointSize, 13)
        XCTAssertEqual(layout.metrics.horizontalPadding, 12)
        let desktopWrappedRow = try XCTUnwrap(layout.layoutAttributesForItem(at: IndexPath(item: 10, section: 0)))
        XCTAssertGreaterThan(desktopWrappedRow.frame.height, wrappedRow.frame.height, "Viewport typography and padding must trigger remeasurement")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    @MainActor
    func testSheetColumnsMatchRenderedWebContentBoxGeometryAndResize() throws {
        let headers = ["Name", "Role", "Department", "Start Date", "Location", "Salary"]
        let preferred: [CGFloat] = [112, 144, 88, 80, 80, 80]
        let layout = SheetFullscreenCollectionLayout()
        let collection = UICollectionView(frame: CGRect(x: 0, y: 0, width: 390, height: 400), collectionViewLayout: layout)
        let rows = [["Alice Johnson", "Senior Engineer", "Engineering", "2023-01-15", "Munich", "€85,000"],
                    ["Bob Smith", "Product Manager", "Product", "2022-06-01", "Berlin", "€92,000"]]
        layout.configure(headers: headers, rows: rows, widths: preferred, viewportWidth: 390)
        layout.prepare()
        XCTAssertEqual(layout.columnWidths[0], 49)
        for index in [1, 2, 4, 5, 6] { XCTAssertEqual(layout.columnWidths[index], 97) }
        // Measured production web geometry: Department must fit its nowrap label + sort control.
        XCTAssertEqual(layout.columnWidths[3], 101.546875, accuracy: 1)
        XCTAssertEqual(layout.collectionViewContentSize.width, 636.546875, accuracy: 1)
        XCTAssertEqual(layout.metrics.letterRowHeight, 33)
        XCTAssertEqual(layout.metrics.contentWidth(for: 97), 80)

        collection.frame.size.width = 1000
        layout.configure(headers: headers, rows: rows, widths: preferred, viewportWidth: 1000)
        layout.prepare()
        XCTAssertEqual(layout.columnWidths[0], 65)
        XCTAssertEqual(layout.columnWidths[1], 112)
        XCTAssertEqual(layout.columnWidths[2], 144)
        XCTAssertEqual(layout.columnWidths[3], 114.6640625, accuracy: 1)
        for index in [4, 5, 6] { XCTAssertEqual(layout.columnWidths[index], 105) }
        XCTAssertEqual(layout.metrics.letterRowHeight, 27)
        XCTAssertEqual(layout.metrics.headerRowHeight, 31.6953125, accuracy: 0.01)
        let firstBody = try XCTUnwrap(layout.layoutAttributesForItem(at: IndexPath(item: 15, section: 0)))
        let secondBody = try XCTUnwrap(layout.layoutAttributesForItem(at: IndexPath(item: 22, section: 0)))
        XCTAssertEqual(firstBody.frame.height, 31.6953125, accuracy: 0.1)
        XCTAssertEqual(secondBody.frame.height, 31.1953125, accuracy: 0.1)

        // A narrow side panel uses window typography but its own available table width.
        layout.configure(headers: headers, rows: rows, widths: preferred, viewportWidth: 1000, availableWidth: 390)
        XCTAssertEqual(layout.columnWidths[1], 105)
        XCTAssertEqual(layout.columnWidths[2], 105)
        let oldDepartmentWidth = layout.columnWidths[3]
        var updatedHeaders = headers
        updatedHeaders[2] = "Department and Business Unit"
        layout.configure(headers: updatedHeaders, rows: rows, widths: preferred, viewportWidth: 1000, availableWidth: 390)
        XCTAssertGreaterThan(layout.columnWidths[3], oldDepartmentWidth,
                             "Header changes must invalidate column and row measurements even if data is unchanged")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    @MainActor
    func testSheetFullscreenHasVisibleCellsInsideVerticalScrollView() async throws {
        var displayedRows: [[String]] = []
        let longRole = String(repeating: "Selectable wrapped content ", count: 12)
        let host = UIHostingController(rootView: ScrollView {
            SheetRenderer(data: ["table": AnyCodable("| Name | Role |\n| --- | --- |\n| Zoe | \(longRole) |\n| Ada | Engineer |")],
                          mode: .fullscreen, onDisplayedRowsChange: { displayedRows = $0 })
        })
        let scene = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first
        let previousKeyWindow = scene?.windows.first { $0.isKeyWindow }
        let hostWindow = scene.map { UIWindow(windowScene: $0) }
            ?? UIWindow(frame: CGRect(x: 0, y: 0, width: 402, height: 874))
        hostWindow.rootViewController = host
        hostWindow.makeKeyAndVisible()
        defer {
            hostWindow.isHidden = true
            hostWindow.rootViewController = nil
            previousKeyWindow?.makeKeyAndVisible()
        }

        func descendants(of view: UIView) -> [UIView] {
            view.subviews.flatMap { [$0] + descendants(of: $0) }
        }
        let cellsMounted = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            MainActor.assumeIsolated {
                host.view.setNeedsLayout()
                host.view.layoutIfNeeded()
                guard let collection = descendants(of: host.view).compactMap({ $0 as? UICollectionView }).first,
                      collection.bounds.height > 0 else { return false }
                collection.layoutIfNeeded()
                return collection.visibleCells.flatMap { descendants(of: $0) }
                    .compactMap { $0 as? UITextView }.contains { !$0.isHidden && $0.text == "Ada" }
            }
        }, object: nil)
        let mountedResult = await XCTWaiter.fulfillment(of: [cellsMounted], timeout: 5)
        XCTAssertEqual(mountedResult, .completed, "The visible host must mount and lay out spreadsheet data cells")
        let collection = try XCTUnwrap(descendants(of: host.view).compactMap { $0 as? UICollectionView }.first)
        collection.layoutIfNeeded()
        XCTAssertGreaterThan(collection.bounds.height, 0, "A ScrollView's unspecified height must not collapse the sheet")
        let visibleValues = collection.visibleCells.flatMap { descendants(of: $0) }
            .compactMap { $0 as? UITextView }.filter { !$0.isHidden }.compactMap(\.text)
        XCTAssertTrue(visibleValues.contains("Ada"), "The table must lay out actual data cells")
        let wrappedTextView = try XCTUnwrap(collection.visibleCells.flatMap { descendants(of: $0) }
            .compactMap { $0 as? UITextView }.first { $0.text == longRole.trimmingCharacters(in: .whitespaces) })
        XCTAssertTrue(wrappedTextView.isSelectable)
        XCTAssertEqual(wrappedTextView.textContainer.maximumNumberOfLines, 0)
        wrappedTextView.layoutManager.ensureLayout(for: wrappedTextView.textContainer)
        let laidOutTextHeight = wrappedTextView.layoutManager.usedRect(for: wrappedTextView.textContainer).height
        XCTAssertGreaterThan(laidOutTextHeight, (wrappedTextView.font?.lineHeight ?? 0) * 2)
        XCTAssertLessThanOrEqual(laidOutTextHeight + wrappedTextView.textContainerInset.top
                                 + wrappedTextView.textContainerInset.bottom, wrappedTextView.bounds.height + 1,
                                 "A fully selectable long cell must fit its measured row without clipping")

        let filterCell = try XCTUnwrap(collection.visibleCells.first { $0.accessibilityIdentifier == "sheet-filter-toggle" })
        let sortCell = try XCTUnwrap(collection.visibleCells.first { $0.accessibilityIdentifier == "sheet-sort-column-0" })
        XCTAssertTrue(filterCell.accessibilityTraits.contains(.button))
        XCTAssertTrue(sortCell.accessibilityTraits.contains(.button))
        XCTAssertEqual(sortCell.accessibilityLabel, "Name", "Sort arrows must be separate glyphs, not emoji in the header label")
        let filterGlyph = try XCTUnwrap(descendants(of: filterCell).first { $0.accessibilityIdentifier == "sheet-filter-glyph" })
        let sortGlyph = try XCTUnwrap(descendants(of: sortCell).first { $0.accessibilityIdentifier == "sheet-sort-glyph" })
        XCTAssertFalse(filterGlyph.isHidden)
        XCTAssertEqual(filterGlyph.bounds.size, CGSize(width: 12, height: 12))
        XCTAssertEqual(sortGlyph.bounds.size, CGSize(width: 10, height: 10))
        XCTAssertEqual(sortGlyph.alpha, 0.35, accuracy: 0.001)
        XCTAssertTrue(sortCell.accessibilityActivate())
        let sorted = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            MainActor.assumeIsolated {
                collection.layoutIfNeeded()
                return displayedRows.first?.first == "Ada" && collection.visibleCells.contains {
                    $0.accessibilityIdentifier == "sheet-sort-column-0" && $0.accessibilityTraits.contains(.selected)
                }
            }
        }, object: nil)
        let sortedResult = await XCTWaiter.fulfillment(of: [sorted], timeout: 5)
        XCTAssertEqual(sortedResult, .completed, "The sort control must call the production sorting callback")
        let activeSort = try XCTUnwrap(collection.visibleCells.first { $0.accessibilityIdentifier == "sheet-sort-column-0" })
        XCTAssertTrue(activeSort.accessibilityTraits.contains(.selected))
        let currentFilter = try XCTUnwrap(collection.visibleCells.first { $0.accessibilityIdentifier == "sheet-filter-toggle" })
        XCTAssertTrue(currentFilter.accessibilityActivate())
        let filtersShown = XCTNSPredicateExpectation(predicate: NSPredicate { _, _ in
            MainActor.assumeIsolated {
                collection.layoutIfNeeded()
                return collection.visibleCells.contains {
                    $0.accessibilityIdentifier == "sheet-filter-toggle" && $0.accessibilityTraits.contains(.selected)
                }
            }
        }, object: nil)
        let filtersResult = await XCTWaiter.fulfillment(of: [filtersShown], timeout: 5)
        XCTAssertEqual(filtersResult, .completed, "The filter control must toggle the production filter bar")
    }
    #endif

    // contract-test: supporting surface=gui.apple assertions=chats.surface.semantic-parity
    func testWikipediaBadgeUsesGeneratedStudyGradientInsteadOfDefaultBlue() throws {
        let appID = try XCTUnwrap(EmbedType.wiki.appId)
        XCTAssertEqual(appID, "study")
        let badge = AppIconView.gradient(forAppId: appID)
        let token = LinearGradient.appStudy
        let badgeGradient = try XCTUnwrap(Mirror(reflecting: badge).descendant("gradient") as? Gradient)
        let tokenGradient = try XCTUnwrap(Mirror(reflecting: token).descendant("gradient") as? Gradient)
        let defaultGradient = try XCTUnwrap(Mirror(reflecting: LinearGradient.primary).descendant("gradient") as? Gradient)
        XCTAssertEqual(badgeGradient.stops, tokenGradient.stops)
        XCTAssertNotEqual(badgeGradient.stops, defaultGradient.stops)
        let badgeStart = try XCTUnwrap(Mirror(reflecting: badge).descendant("startPoint") as? UnitPoint)
        let tokenStart = try XCTUnwrap(Mirror(reflecting: token).descendant("startPoint") as? UnitPoint)
        let badgeEnd = try XCTUnwrap(Mirror(reflecting: badge).descendant("endPoint") as? UnitPoint)
        let tokenEnd = try XCTUnwrap(Mirror(reflecting: token).descendant("endPoint") as? UnitPoint)
        XCTAssertEqual(badgeStart, tokenStart)
        XCTAssertEqual(badgeEnd, tokenEnd)
        XCTAssertEqual(AppIconView.iconName(forAppId: appID), "study")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testSheetBadgeUsesWebSheetsGradientAndCanonicalIcon() throws {
        let badge = AppIconView.gradient(forAppId: "sheets")
        let token = LinearGradient.appSheets
        // SwiftUI keeps LinearGradient's stored gradient package-private.
        // Inspect its value to verify the selected colors/stops without a renderer.
        let badgeGradient = try XCTUnwrap(Mirror(reflecting: badge).descendant("gradient") as? Gradient)
        let tokenGradient = try XCTUnwrap(Mirror(reflecting: token).descendant("gradient") as? Gradient)
        XCTAssertEqual(badgeGradient.stops, tokenGradient.stops)
        XCTAssertEqual(AppIconView.iconName(forAppId: "sheets"), "sheets")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testCanonicalEmbedIDPrecedesStorageRowIDAndLocalRecordsRetainIDFallback() throws {
        let databaseID = UUID().uuidString.lowercased()
        let canonicalID = UUID().uuidString.lowercased()
        for convertFromSnakeCase in [false, true] {
            let decoder = JSONDecoder()
            if convertFromSnakeCase { decoder.keyDecodingStrategy = .convertFromSnakeCase }
            let stored = try decoder.decode(EmbedRecord.self, from: JSONSerialization.data(withJSONObject: [
                "id": databaseID, "embed_id": canonicalID, "status": "finished", "version_number": 8,
                "encrypted_type": "synthetic-type-ciphertext", "encrypted_content": "synthetic-content-ciphertext"
            ]))
            XCTAssertEqual(stored.id, canonicalID)
            XCTAssertEqual(stored.status, .finished)
            XCTAssertEqual(stored.versionNumber, 8)
            XCTAssertEqual(EmbedRecord.relatedRecords(referencedIds: [canonicalID], from: [stored], context: "wireIdentity").map(\.id),
                [canonicalID])
            XCTAssertTrue(EmbedRecord.relatedRecords(referencedIds: [databaseID], from: [stored], context: "wireIdentity").isEmpty)
            let local = try decoder.decode(EmbedRecord.self, from: JSONSerialization.data(withJSONObject: [
                "id": canonicalID, "type": "code-code", "status": "finished"
            ]))
            XCTAssertEqual(local.id, canonicalID)
        }
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testBackendCodeAliasRoutesDecryptedSourceToCodeRendererAndKeepsProcessingStatus() throws {
        let row = #"{"embed_id":"synthetic-code","type":"code","status":"processing","encrypted_content":"ciphertext"}"#
        let record = try JSONDecoder().decode(EmbedRecord.self, from: Data(row.utf8))
        XCTAssertEqual(record.type, "code-code")
        XCTAssertEqual(EmbedType.normalized(rawValue: "code"), .codeCode)
        XCTAssertEqual(EmbedType.normalized(rawValue: record.type), .codeCode)
        XCTAssertEqual(record.status, .processing)
        let decrypted = record.decryptedCopy(
            content: #"{"type":"code","filename":"main.py","language":"python","code":"print('ready')"}"#,
            type: "code")
        XCTAssertEqual(decrypted.type, "code-code")
        XCTAssertEqual(decrypted.status, .processing, "Hydration must not manufacture a finished server status")
        XCTAssertEqual(AppleCodeEmbedContent(data: decrypted.rawData).code, "print('ready')")
        XCTAssertEqual(AppleCodeEmbedContent(data: decrypted.rawData).filename, "main.py")
    }

    // contract-test: supporting surface=gui.apple assertions=chats.rendering.assistant-document-convergence
    func testBackendSheetAliasAndQuotedToonScalarsHydrateMultilineTable() throws {
        let table = "| Name | Note |\n| --- | --- |\n| Ada | A \\\"quoted\\\" path \\\\ |"
        let encodedTable = String(decoding: try JSONEncoder().encode(table), as: UTF8.self)
        let fields = EmbedRecord.parseContent("type: sheet\ntitle: Team\ntable: \(encodedTable)")
        XCTAssertEqual(fields["table"] as? String, table)
        XCTAssertEqual(EmbedType.normalized(rawValue: "sheet"), .sheetsSheet)
        let record = EmbedRecord(id: "synthetic-sheet", type: "sheet", status: .finished, data: nil,
                                 parentEmbedId: nil, appId: "sheets", skillId: "sheet", embedIds: nil, createdAt: nil)
            .decryptedCopy(content: "type: sheet\ntitle: Team\ntable: \(encodedTable)", type: "sheet")
        XCTAssertEqual(record.type, EmbedType.sheetsSheet.rawValue)
        let parsed = ParsedSheetTable(data: record.rawData)
        XCTAssertEqual(parsed.headers, ["Name", "Note"])
        XCTAssertEqual(parsed.rows.count, 1)
    }
}
