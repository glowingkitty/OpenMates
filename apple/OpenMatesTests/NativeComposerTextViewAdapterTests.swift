// Red contract tests for the native TextKit 2 composer view adapter.
// UIKit and AppKit must expose the same controller-driven editing semantics.
// Accessibility labels and actions are injected synthetic fixture values.
// Embed accessibility order follows the canonical composer document order.
// Adapter synchronization must retain controller and attachment identities.

import Foundation
import SwiftUI
import XCTest
@testable import OpenMates

#if canImport(UIKit)
import UIKit
#elseif canImport(AppKit)
import AppKit
#endif

@MainActor
final class NativeComposerTextViewAdapterTests: XCTestCase {
    // contract-test: supporting surface=gui.apple assertions=message-input.layout.responsive-parity
    func testActualNativeScrollingEnablesAndRemovesTopMaskWithoutReplacingDelegateOrSelection() throws {
        #if canImport(UIKit)
        let session = NativeComposerSession()
        session.replaceMarkdown(String(repeating: "Synthetic scroll line\n", count: 30))
        let coordinator = NativeComposerEditorView.Coordinator(session: session, accessibilityHint: "Synthetic")
        let view = coordinator.adapter.makePlatformView()
        view.frame = CGRect(x: 0, y: 0, width: 300, height: 120)
        view.isScrollEnabled = true
        view.layoutIfNeeded()
        view.selectedRange = NSRange(location: 2, length: 3)
        let originalRevision = session.controller.revision
        coordinator.installScrollFade(on: view)
        view.setContentOffset(.zero, animated: false)
        coordinator.updateScrollFade(view)
        XCTAssertNil(view.layer.mask, "Unscrolled first line must remain fully opaque")
        view.setContentOffset(CGPoint(x: 0, y: 100), animated: false)
        coordinator.updateScrollFade(view)
        let mask = try XCTUnwrap(view.layer.mask as? CAGradientLayer)
        let colors = try XCTUnwrap(mask.colors as? [CGColor])
        XCTAssertEqual(try XCTUnwrap(colors.first).alpha, 0)
        XCTAssertEqual(try XCTUnwrap(colors.last).alpha, 1, "Bottom/footer must remain opaque")
        XCTAssertTrue(view.delegate === coordinator.adapter)
        XCTAssertEqual(view.selectedRange, NSRange(location: 2, length: 3))
        XCTAssertEqual(session.controller.revision, originalRevision)
        view.setContentOffset(.zero, animated: false)
        coordinator.updateScrollFade(view)
        XCTAssertNil(view.layer.mask)
        NativeComposerEditorView.dismantleUIView(view, coordinator: coordinator)
        XCTAssertNil(coordinator.boundsObservation)
        #elseif canImport(AppKit)
        let session = NativeComposerSession(canonicalMarkdown: String(repeating: "Synthetic scroll line\n", count: 30))
        let coordinator = NativeComposerEditorView.Coordinator(session: session, accessibilityHint: "Synthetic")
        let view = coordinator.adapter.makePlatformView()
        view.setFrameSize(NSSize(width: 300, height: 1200))
        view.setSelectedRange(NSRange(location: 2, length: 3))
        let scrollView = NSScrollView(frame: CGRect(x: 0, y: 0, width: 300, height: 120))
        scrollView.documentView = view
        let originalRevision = session.controller.revision
        coordinator.installScrollFade(on: scrollView)
        scrollView.contentView.scroll(to: .zero)
        coordinator.updateScrollFade(scrollView)
        XCTAssertNil(scrollView.contentView.layer?.mask)
        scrollView.contentView.scroll(to: CGPoint(x: 0, y: 100))
        coordinator.updateScrollFade(scrollView)
        let mask = try XCTUnwrap(scrollView.contentView.layer?.mask as? CAGradientLayer)
        let colors = try XCTUnwrap(mask.colors as? [CGColor])
        XCTAssertEqual(try XCTUnwrap(colors.first).alpha, 0)
        XCTAssertEqual(try XCTUnwrap(colors.last).alpha, 1)
        XCTAssertTrue(view.delegate === coordinator.adapter)
        XCTAssertEqual(view.selectedRange(), NSRange(location: 2, length: 3))
        XCTAssertEqual(session.controller.revision, originalRevision)
        scrollView.contentView.scroll(to: .zero)
        coordinator.updateScrollFade(scrollView)
        XCTAssertNil(scrollView.contentView.layer?.mask)
        NativeComposerEditorView.dismantleNSView(scrollView, coordinator: coordinator)
        XCTAssertNil(coordinator.boundsObserver)
        #endif
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.layout.responsive-parity
    func testPlaintextControlLaneKeepsFirstLineAtTopAndStableThroughNativeScrolling() throws {
        let session = NativeComposerSession(canonicalMarkdown: String(repeating: "Synthetic long line wraps around a stable right lane.\n", count: 20))
        let coordinator = NativeComposerEditorView.Coordinator(session: session, accessibilityHint: "Synthetic")
        let view = coordinator.adapter.makePlatformView()
        coordinator.reservesControlLane = true
        let revision = session.controller.revision
        #if canImport(UIKit)
        view.frame = CGRect(x: 0, y: 0, width: 362, height: 120)
        view.textContainerInset = UIEdgeInsets(top: 14, left: 12, bottom: 14, right: 12)
        coordinator.applyControlLane(to: view)
        view.layoutIfNeeded()
        let first = view.caretRect(for: view.beginningOfDocument)
        XCTAssertLessThan(first.minY, 24, "Plain text must start at the top, without a blank control row")
        let selection = view.textRange(from: view.beginningOfDocument,
            to: try XCTUnwrap(view.position(from: view.beginningOfDocument, offset: 50)))
        let rects = view.selectionRects(for: try XCTUnwrap(selection))
        XCTAssertFalse(rects.isEmpty)
        XCTAssertTrue(rects.allSatisfy { $0.rect.maxX <= 362 - 44 - 15 - 4 }, "Actual text never enters the icon hit lane")
        let inset = view.textContainerInset
        let selectionBeforeScroll = view.selectedRange
        view.isScrollEnabled = true
        view.setContentOffset(CGPoint(x: 0, y: 100), animated: false)
        coordinator.applyControlLane(to: view)
        XCTAssertEqual(view.textContainerInset, inset, "No moving exclusion/reflow on scroll")
        XCTAssertEqual(view.selectedRange, selectionBeforeScroll)
        XCTAssertTrue(view.delegate === coordinator.adapter)
        #elseif canImport(AppKit)
        view.setFrameSize(NSSize(width: 362, height: 1200))
        view.textContainerInset = NSSize(width: 12, height: 14)
        coordinator.applyControlLane(to: view, width: 362)
        let container = try XCTUnwrap(view.textContainer)
        let laneWidth = container.size.width
        let selectionBeforeScroll = view.selectedRange()
        XCTAssertLessThanOrEqual(laneWidth + view.textContainerInset.width, 362 - 44 - 15 - 4)
        XCTAssertLessThan(view.textContainerInset.height, 24)
        let scroll = NSScrollView(frame: CGRect(x: 0, y: 0, width: 362, height: 120))
        scroll.documentView = view
        scroll.contentView.scroll(to: CGPoint(x: 0, y: 100))
        coordinator.applyControlLane(to: view, width: 362)
        XCTAssertEqual(container.size.width, laneWidth)
        XCTAssertEqual(view.selectedRange(), selectionBeforeScroll)
        XCTAssertTrue(view.delegate === coordinator.adapter)
        #endif
        XCTAssertEqual(session.controller.revision, revision)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.layout.responsive-parity
    func testNativeOverflowBoundaryClearRotationAndMeasurementPreserveLiveView() throws {
        let session = NativeComposerSession()
        let coordinator = NativeComposerEditorView.Coordinator(session: session, accessibilityHint: "Synthetic")
        let view = coordinator.adapter.makePlatformView()
        let limit = MessageComposerMetric.collapsedTextEditorMaxHeight
        #if canImport(UIKit)
        view.frame = CGRect(x: 0, y: 0, width: 362, height: limit)
        view.textContainerInset = UIEdgeInsets(top: 14, left: 12, bottom: 14, right: 12)
        #elseif canImport(AppKit)
        view.setFrameSize(NSSize(width: 362, height: limit))
        view.textContainerInset = NSSize(width: 12, height: 14)
        #endif
        func measure(_ text: String, width: CGFloat = 362) -> Bool {
            session.replaceMarkdown(text); coordinator.adapter.synchronize(view)
            return coordinator.measuredOverflow(view, width: width, limit: limit)
        }
        XCTAssertFalse(measure(""))
        XCTAssertFalse(measure("Short text"))
        XCTAssertFalse(measure("One\nTwo\nThree"), "Full three-line boundary remains visible")
        XCTAssertTrue(measure("One\nTwo\nThree\nFour\nFive"))
        XCTAssertFalse(measure(""), "Clearing removes overflow")
        let long = String(repeating: "word ", count: 32)
        XCTAssertTrue(measure(long, width: 200))
        XCTAssertFalse(measure(long, width: 900), "Rotation/width change re-evaluates actual wrapping")
        session.replaceMarkdown("One\nTwo\nThree"); coordinator.adapter.synchronize(view)
        coordinator.reservesControlLane = true
        #if canImport(UIKit)
        coordinator.applyControlLane(to: view)
        let bounds = view.bounds, inset = view.textContainerInset, selection = view.selectedRange, offset = view.contentOffset
        #elseif canImport(AppKit)
        coordinator.applyControlLane(to: view, width: 362)
        let bounds = view.bounds, inset = view.textContainerInset, selection = view.selectedRange()
        let container = try XCTUnwrap(view.textContainer); let size = container.size
        #endif
        let revision = session.controller.revision
        XCTAssertFalse(coordinator.measuredOverflow(view, width: 362, limit: limit),
            "Icon lane cannot make a full-width three-line baseline toggle overflow")
        XCTAssertFalse(coordinator.measuredOverflow(view, width: 362, limit: limit))
        XCTAssertEqual(view.bounds, bounds); XCTAssertEqual(view.textContainerInset, inset)
        XCTAssertTrue(view.delegate === coordinator.adapter); XCTAssertEqual(session.controller.revision, revision)
        #if canImport(UIKit)
        XCTAssertEqual(view.selectedRange, selection); XCTAssertEqual(view.contentOffset, offset)
        #elseif canImport(AppKit)
        XCTAssertEqual(view.selectedRange(), selection); XCTAssertEqual(container.size, size)
        #endif
        session.replaceMarkdown("")
        try session.insertPendingEmbed(nodeID: "synthetic-one", embedType: "image", title: "Synthetic image")
        coordinator.adapter.synchronize(view)
        XCTAssertFalse(coordinator.measuredOverflow(view, width: 362, limit: MessageComposerMetric.embedTextEditorMaxHeight),
            "One actual200pt card fits the native collapsed media viewport")
        try session.insertPendingEmbed(nodeID: "synthetic-two", embedType: "recording", title: "Synthetic recording")
        coordinator.adapter.synchronize(view)
        XCTAssertTrue(coordinator.measuredOverflow(view, width: 362, limit: MessageComposerMetric.embedTextEditorMaxHeight),
            "Two real media rows overflow and expose expand")
        XCTAssertFalse(coordinator.measuredOverflow(view, width: 362, limit: 900),
            "Expanded native viewport updates overflow while host keeps collapse reachable")
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.focus.parent-state
    func testCreatesTextKit2PlatformViewAndSynchronizesContentAndSelection() throws {
        let controller = try makeController()
        let adapter = makeAdapter(controller: controller)
        let textView = adapter.makePlatformView()

        #if canImport(UIKit)
        XCTAssertNotNil(textView.textLayoutManager)
        XCTAssertEqual(textView.attributedText.string, controller.attributedString.string)
        XCTAssertEqual(textView.selectedRange, controller.selection)
        XCTAssertEqual(textView.accessibilityIdentifier, "message-editor")
        XCTAssertEqual(textView.accessibilityLabel, "Synthetic message input")
        XCTAssertEqual(textView.accessibilityHint, "Synthetic editing hint")
        #elseif canImport(AppKit)
        XCTAssertNotNil(textView.textLayoutManager)
        XCTAssertEqual(try XCTUnwrap(textView.textStorage).string, controller.attributedString.string)
        XCTAssertEqual(textView.selectedRange(), controller.selection)
        XCTAssertEqual(textView.accessibilityIdentifier(), "message-editor")
        XCTAssertEqual(textView.accessibilityLabel(), "Synthetic message input")
        XCTAssertEqual(textView.accessibilityHelp(), "Synthetic editing hint")
        #endif

        try controller.setSelection(NSRange(location: 1, length: 2))
        adapter.synchronize(textView)

        #if canImport(UIKit)
        XCTAssertEqual(textView.selectedRange, NSRange(location: 1, length: 2))
        #elseif canImport(AppKit)
        XCTAssertEqual(textView.selectedRange(), NSRange(location: 1, length: 2))
        #endif
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send
    func testExposesEmbedAccessibilityInDocumentOrderWithInjectedCustomActions() throws {
        let controller = try makeController()
        let recorder = AccessibilityActionRecorder()
        let adapter = makeAdapter(controller: controller, recorder: recorder)
        let textView = adapter.makePlatformView()

        XCTAssertEqual(
            adapter.embedAccessibilityElements.map(\.nodeID),
            ["composer:embed:first", "composer:embed:second"]
        )
        XCTAssertEqual(
            adapter.embedAccessibilityElements.map(\.label),
            ["Synthetic image, finished", "Synthetic PDF, finished"]
        )
        XCTAssertEqual(
            adapter.embedAccessibilityElements.map(\.actionNames),
            [["Synthetic remove"], ["Synthetic remove"]]
        )

        #if canImport(UIKit)
        let platformElements = try XCTUnwrap(
            textView.accessibilityElements as? [UIAccessibilityElement]
        )
        XCTAssertEqual(
            platformElements.compactMap(\.accessibilityLabel),
            ["Synthetic image, finished", "Synthetic PDF, finished"]
        )
        XCTAssertEqual(
            platformElements.map { $0.accessibilityCustomActions?.map(\.name) ?? [] },
            [["Synthetic remove"], ["Synthetic remove"]]
        )
        #endif

        XCTAssertTrue(adapter.performAccessibilityAction(
            named: "Synthetic remove",
            forEmbedID: "composer:embed:second"
        ))
        XCTAssertEqual(recorder.nodeIDs, ["composer:embed:second"])
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.embeds.gated-send
    func testEmbedStatusSynchronizationRetainsControllerAndPlatformViewIdentity() throws {
        let controller = try makeController()
        let adapter = makeAdapter(controller: controller)
        let textView = adapter.makePlatformView()
        let platformViewIdentity = ObjectIdentifier(textView)

        try controller.updateEmbed(id: "composer:embed:first", status: "processing")
        adapter.synchronize(textView)

        XCTAssertTrue(adapter.controller === controller)
        XCTAssertEqual(ObjectIdentifier(textView), platformViewIdentity)
        XCTAssertEqual(
            adapter.embedAccessibilityElements.map(\.label),
            ["Synthetic image, processing", "Synthetic PDF, finished"]
        )
        #if canImport(UIKit)
        XCTAssertEqual(textView.attributedText.string, controller.attributedString.string)
        #elseif canImport(AppKit)
        XCTAssertEqual(try XCTUnwrap(textView.textStorage).string, controller.attributedString.string)
        #endif
    }

    #if canImport(UIKit)
    // contract-test: direct surface=gui.apple assertions=message-input.recording.lifecycle,message-input.embeds.gated-send
    func testHostedAccessibilityRetainsPreviewChildrenAcrossRecordingRetry() throws {
        let controller = try NativeComposerController(document: ComposerDocumentV1(version: 1, nodes: [
            ComposerNodeV1(kind: "embed", id: "composer:retry-recording", embedType: "recording",
                status: "error", display: ComposerEmbedDisplayV1(title: "Synthetic recording", mediaKind: "recording"))
        ]), selection: NSRange(location: 1, length: 0))
        let adapter = makeAdapter(controller: controller, accessibilityStrategy: .hostedAttachments)
        let textView = adapter.makePlatformView()
        // Exercise UIKit's child traversal policy with a hosted preview surface,
        // rather than replacing its playback controls with semantic descriptors.
        let hosted = UIHostingController(rootView: Button("Play synthetic recording") { })
        hosted.view.accessibilityIdentifier = "synthetic-hosted-recording"
        textView.addSubview(hosted.view)
        let hostedIdentity = ObjectIdentifier(hosted.view)
        let editorIdentity = ObjectIdentifier(textView)
        XCTAssertNil(textView.accessibilityElements)
        XCTAssertTrue(hosted.view.isDescendant(of: textView))
        XCTAssertEqual(adapter.embedAccessibilityElements.first?.label, "Synthetic recording, error")

        try controller.updateEmbed(id: "composer:retry-recording", status: "finished")
        adapter.synchronize(textView)

        XCTAssertEqual(ObjectIdentifier(textView), editorIdentity)
        XCTAssertEqual(ObjectIdentifier(hosted.view), hostedIdentity)
        XCTAssertTrue(hosted.view.isDescendant(of: textView))
        XCTAssertFalse(hosted.view.accessibilityElementsHidden)
        XCTAssertNil(textView.accessibilityElements,
                     "Status re-projection must preserve native hosted-child traversal")
        XCTAssertEqual(adapter.embedAccessibilityElements.first?.label, "Synthetic recording, finished")
        XCTAssertEqual(textView.attributedText.string, controller.attributedString.string)
    }

    // contract-test: direct surface=gui.apple assertions=message-input.recording.lifecycle
    func testResolvedEmbedReprojectsAttachmentWithoutWaitingForTyping() throws {
        let controller = try makeController()
        let adapter = makeAdapter(controller: controller)
        let textView = adapter.makePlatformView()
        let staleProjection = NSAttributedString.Key("synthetic-stale-attachment-projection")
        textView.textStorage.addAttribute(staleProjection, value: true, range: NSRange(location: 1, length: 1))

        let original = try XCTUnwrap(controller.document.nodes.first { $0.id == "composer:embed:first" })
        let resolved = ComposerNodeV1(
            kind: "embed",
            id: original.id,
            embedType: original.embedType,
            status: "finished",
            contentRef: "embed:resolved-recording",
            referenceOnly: true,
            canonicalSource: "```json\n{\"type\":\"recording\",\"embed_id\":\"resolved-recording\"}\n```",
            display: ComposerEmbedDisplayV1(title: "Resolved recording", mediaKind: "recording")
        )
        let originalString = textView.attributedText.string
        try controller.replaceEmbed(id: original.id, with: resolved)
        adapter.synchronize(textView)

        XCTAssertEqual(textView.attributedText.string, originalString)
        XCTAssertNil(textView.attributedText.attribute(staleProjection, at: 1, effectiveRange: nil))
        XCTAssertEqual(textView.selectedRange, controller.selection)
        XCTAssertEqual(adapter.embedAccessibilityElements.first?.label, "Resolved recording, finished")
    }

    // contract-test: direct surface=gui.apple assertions=message-input.recording.lifecycle,message-input.embeds.gated-send
    func testHostedEmbedOwnsInteractionInsteadOfUITextViewAttachmentMenu() throws {
        let controller = try makeController()
        let adapter = makeAdapter(controller: controller)
        let textView = adapter.makePlatformView()
        let attachment = try XCTUnwrap(
            textView.attributedText.attribute(
                .attachment,
                at: 1,
                effectiveRange: nil
            ) as? ComposerTextAttachment
        )

        XCTAssertFalse(NativeComposerTextView.shouldUseTextViewInteraction(for: attachment))
        XCTAssertTrue(NativeComposerTextView.shouldUseTextViewInteraction(for: NSTextAttachment()))
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.embeds.gated-send
    func testAttachmentProviderInstallsOneLongPressScopedToContainingEditor() throws {
        let controller = try makeController()
        let textView = makeAdapter(controller: controller).makePlatformView()
        let attachment = try XCTUnwrap(textView.attributedText.attribute(.attachment, at: 1, effectiveRange: nil) as? ComposerTextAttachment)
        let location = try XCTUnwrap(textView.textLayoutManager?.textContentManager?.documentRange.location)
        let provider = try XCTUnwrap(attachment.viewProvider(for: textView, location: location, textContainer: textView.textContainer))
        provider.loadView()
        let host = try XCTUnwrap(provider.view)
        textView.addSubview(host)
        let recognizers = host.gestureRecognizers?.filter { $0.delegate is ComposerAttachmentLongPressBridge } ?? []
        XCTAssertEqual(recognizers.count, 1)
        let recognizer = try XCTUnwrap(recognizers.first as? UILongPressGestureRecognizer)
        let bridge = try XCTUnwrap(recognizer.delegate as? ComposerAttachmentLongPressBridge)
        XCTAssertTrue(ComposerAttachmentLongPressBridge.install(on: host, attachment: attachment) === bridge)
        XCTAssertEqual(host.gestureRecognizers?.filter { $0.delegate is ComposerAttachmentLongPressBridge }.count, 1)
        XCTAssertEqual(recognizer.minimumPressDuration, 0.6)
        XCTAssertFalse(recognizer.cancelsTouchesInView)

        let editorGesture = UILongPressGestureRecognizer()
        textView.addGestureRecognizer(editorGesture)
        XCTAssertTrue(bridge.gestureRecognizer(recognizer, shouldRecognizeSimultaneouslyWith: editorGesture))
        let child = UIView()
        host.addSubview(child)
        let childGesture = UITapGestureRecognizer()
        child.addGestureRecognizer(childGesture)
        XCTAssertTrue(bridge.gestureRecognizer(recognizer, shouldRecognizeSimultaneouslyWith: childGesture))
        let unrelatedEditor = UITextView(usingTextLayoutManager: true)
        let unrelatedGesture = UILongPressGestureRecognizer()
        unrelatedEditor.addGestureRecognizer(unrelatedGesture)
        XCTAssertFalse(bridge.gestureRecognizer(recognizer, shouldRecognizeSimultaneouslyWith: unrelatedGesture))
        XCTAssertFalse(bridge.gestureRecognizer(editorGesture, shouldRecognizeSimultaneouslyWith: childGesture))
        XCTAssertFalse(bridge.gestureRecognizer(recognizer, shouldRecognizeSimultaneouslyWith: UITapGestureRecognizer()))
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.recording.lifecycle,message-input.embeds.gated-send
    func testHostedLongPressTogglesRemovalOncePerPressWithoutRemovingAttachment() throws {
        let attachment = ComposerTextAttachment(node: fixtureEmbed(id: "recording", title: "Synthetic recording", embedType: "recording"))
        let host = UIView()
        let bridge = ComposerAttachmentLongPressBridge.install(on: host, attachment: attachment)
        var removals = 0
        attachment.updateActions(AppleComposerEmbedActions(onOpen: { _ in }, onRetry: { _ in }, onRemove: { _ in removals += 1 }))
        XCTAssertFalse(attachment.showsRemovalAction)
        bridge.handle(state: .possible)
        XCTAssertFalse(attachment.showsRemovalAction)
        bridge.handle(state: .began)
        XCTAssertTrue(attachment.showsRemovalAction)
        bridge.handle(state: .began)
        bridge.handle(state: .changed)
        bridge.handle(state: .ended)
        XCTAssertTrue(attachment.showsRemovalAction)
        bridge.handle(state: .began)
        XCTAssertFalse(attachment.showsRemovalAction)
        bridge.handle(state: .cancelled)
        bridge.handle(state: .began)
        XCTAssertTrue(attachment.showsRemovalAction)
        bridge.handle(state: .failed)
        attachment.setShowsRemovalAction(false)
        bridge.handle(state: .began)
        XCTAssertTrue(attachment.showsRemovalAction)
        XCTAssertEqual(removals, 0, "Recognition must reveal the explicit Remove action rather than delete the atom")
        XCTAssertEqual(attachment.nodeSnapshot?.id, "recording")
    }
    #endif

    // contract-test: supporting surface=gui.apple assertions=message-input.focus.parent-state
    func testPlatformEditsAndSelectionChangesSynchronizeBackToController() throws {
        let controller = try makeController()
        let adapter = makeAdapter(controller: controller)
        let textView = adapter.makePlatformView()

        #if canImport(UIKit)
        commitUIKitEdit(adapter, textView: textView, range: NSRange(location: 0, length: 1), replacement: "Z")
        XCTAssertEqual(textView.attributedText.string, "Z\u{FFFC}B\u{FFFC}C")
        textView.selectedRange = NSRange(location: 2, length: 1)
        adapter.textViewDidChangeSelection(textView)
        #elseif canImport(AppKit)
        XCTAssertFalse(adapter.textView(
            textView,
            shouldChangeTextIn: NSRange(location: 0, length: 1),
            replacementString: "Z"
        ))
        XCTAssertEqual(textView.string, "Z\u{FFFC}B\u{FFFC}C")
        textView.setSelectedRange(NSRange(location: 2, length: 1))
        adapter.textViewDidChangeSelection(Notification(name: NSTextView.didChangeSelectionNotification, object: textView))
        #endif

        XCTAssertEqual(controller.attributedString.string, "Z\u{FFFC}B\u{FFFC}C")
        XCTAssertEqual(controller.selection, NSRange(location: 2, length: 1))
        XCTAssertNil(adapter.lastControllerError)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.layout.responsive-parity
    func testTypedTextRetainsWebTypographyAndSemanticForegroundColor() throws {
        FontRegistration.registerFonts()
        let controller = try makeController()
        let adapter = makeAdapter(controller: controller)
        let textView = adapter.makePlatformView()

        #if canImport(UIKit)
        commitUIKitEdit(adapter, textView: textView, range: NSRange(location: 0, length: 1), replacement: "Z")
        let attributes = textView.attributedText.attributes(at: 0, effectiveRange: nil)
        let font = try XCTUnwrap(attributes[.font] as? UIFont)
        let foregroundColor = try XCTUnwrap(attributes[.foregroundColor] as? UIColor)
        let paragraphStyle = try XCTUnwrap(attributes[.paragraphStyle] as? NSParagraphStyle)
        let expectedColor = UIColor(Color.fontPrimary)
        let darkTraits = UITraitCollection(userInterfaceStyle: .dark)

        XCTAssertEqual(font.fontName, "LexendDeca-Medium")
        XCTAssertEqual(font.pointSize, 16, accuracy: 0.01)
        XCTAssertEqual(paragraphStyle.minimumLineHeight, 25.6, accuracy: 0.01)
        XCTAssertEqual(paragraphStyle.maximumLineHeight, 25.6, accuracy: 0.01)
        XCTAssertEqual(
            foregroundColor.resolvedColor(with: darkTraits),
            expectedColor.resolvedColor(with: darkTraits)
        )
        XCTAssertEqual((textView.typingAttributes[.font] as? UIFont)?.fontName, "LexendDeca-Medium")
        #elseif canImport(AppKit)
        XCTAssertFalse(adapter.textView(
            textView,
            shouldChangeTextIn: NSRange(location: 0, length: 1),
            replacementString: "Z"
        ))
        let attributes = try XCTUnwrap(textView.textStorage).attributes(at: 0, effectiveRange: nil)
        let font = try XCTUnwrap(attributes[.font] as? NSFont)
        let paragraphStyle = try XCTUnwrap(attributes[.paragraphStyle] as? NSParagraphStyle)

        XCTAssertEqual(font.fontName, "LexendDeca-Medium")
        XCTAssertEqual(font.pointSize, 16, accuracy: 0.01)
        XCTAssertEqual(paragraphStyle.minimumLineHeight, 25.6, accuracy: 0.01)
        XCTAssertEqual(paragraphStyle.maximumLineHeight, 25.6, accuracy: 0.01)
        XCTAssertNotNil(attributes[.foregroundColor] as? NSColor)
        #endif
    }

    #if canImport(UIKit)
    // contract-test: supporting surface=gui.apple assertions=message-input.focus.parent-state
    func testUIKitAccessibilityTracksNativeTextWithoutStaleOverride() throws {
        let controller = try NativeComposerController(
            document: ComposerDocumentV1(version: 1, nodes: [.text(id: "text-1", source: "Prefix")]),
            selection: NSRange(location: 6, length: 0)
        )
        let adapter = makeAdapter(controller: controller)
        let textView = adapter.makePlatformView()
        let nativeTextView = UITextView(usingTextLayoutManager: true)
        nativeTextView.text = "Prefix and suffix"
        // Native storage can finish a keyboard edit before the next adapter refresh.
        textView.textStorage.append(NSAttributedString(string: " and suffix"))
        XCTAssertEqual(textView.text, nativeTextView.text)
        XCTAssertEqual(textView.accessibilityValue, nativeTextView.accessibilityValue,
                       "Adapter must retain standard UITextView dynamic accessibility")
    }

    // UIKit must commit replacement ranges itself before canonical text is published.
    // This models keyboard correction followed by continued typing, without a second
    // adapter mutation of the native storage or selection during shouldChange.
    // contract-test: supporting surface=gui.apple assertions=message-input.focus.parent-state
    func testUIKitCommitsCorrectionAndContinuedTypingExactlyOnce() throws {
        let controller = try NativeComposerController(
            document: ComposerDocumentV1(version: 1, nodes: [.text(id: "text-1", source: "Reply with one short sentnce")]),
            selection: NSRange(location: 28, length: 0)
        )
        let adapter = makeAdapter(controller: controller)
        let textView = adapter.makePlatformView()
        var published: [String] = []
        adapter.onCanonicalMarkdownChange = { published.append($0) }

        commitUIKitEdit(adapter, textView: textView, range: NSRange(location: 21, length: 7), replacement: "sentence")
        commitUIKitEdit(adapter, textView: textView, range: textView.selectedRange, replacement: ": Hello from Osaka.")

        let expected = "Reply with one short sentence: Hello from Osaka."
        XCTAssertEqual(textView.text, expected)
        XCTAssertEqual(controller.attributedString.string, expected)
        XCTAssertEqual(published, ["Reply with one short sentence", expected])
        XCTAssertEqual(textView.selectedRange, NSRange(location: expected.utf16.count, length: 0))
    }

    private func commitUIKitEdit(
        _ adapter: NativeComposerTextView,
        textView: UITextView,
        range: NSRange,
        replacement: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        let originalText = textView.text
        let originalSelection = textView.selectedRange
        XCTAssertTrue(adapter.textView(textView, shouldChangeTextIn: range, replacementText: replacement), file: file, line: line)
        XCTAssertEqual(textView.text, originalText, "Delegate must leave the native transaction to UIKit", file: file, line: line)
        XCTAssertEqual(textView.selectedRange, originalSelection, file: file, line: line)
        // A SwiftUI refresh during the transaction must not pre-apply the edit.
        adapter.synchronize(textView)
        XCTAssertEqual(textView.text, originalText, file: file, line: line)
        textView.textStorage.replaceCharacters(in: range, with: NSAttributedString(string: replacement, attributes: textView.typingAttributes))
        textView.selectedRange = NSRange(location: range.location + replacement.utf16.count, length: 0)
        adapter.textViewDidChange(textView)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.focus.parent-state
    func testEquivalentSynchronizationPreservesAttributedTextWithoutAutoCapitalization() throws {
        let controller = try NativeComposerController(
            document: ComposerDocumentV1(version: 1, nodes: [.text(id: "text-1", source: "Hello")]),
            selection: NSRange(location: 5, length: 0)
        )
        let adapter = makeAdapter(controller: controller)
        let textView = adapter.makePlatformView()
        let sentinel = NSAttributedString.Key("synthetic-input-trait-sentinel")
        textView.textStorage.addAttribute(sentinel, value: true, range: NSRange(location: 0, length: 1))

        XCTAssertEqual(textView.autocapitalizationType, .none)
        try controller.loadDocument(ComposerDocumentV1(version: 1, nodes: [.text(id: "text-2", source: "Hello")]))
        adapter.synchronize(textView)

        XCTAssertEqual(textView.attributedText.attribute(sentinel, at: 0, effectiveRange: nil) as? Bool, true)
        XCTAssertEqual(textView.autocapitalizationType, .none)
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.privacy-context,message-input.recording.lifecycle
    func testEqualSynchronizationDoesNotEditTextStorageAndPIIChangesStillApply() throws {
        let controller = try NativeComposerController(
            document: ComposerDocumentV1(version: 1, nodes: [
                .text(id: "text", source: "alice@example.com "),
                fixtureEmbed(id: "recording", title: "Synthetic recording", embedType: "recording")
            ]), selection: NSRange(location: 0, length: 0))
        let adapter = makeAdapter(controller: controller)
        let textView = adapter.makePlatformView()
        let edits = TextStorageEditCounter()
        let observer = NotificationCenter.default.addObserver(
            forName: NSTextStorage.didProcessEditingNotification,
            object: textView.textStorage, queue: nil
        ) { _ in MainActor.assumeIsolated { edits.count += 1 } }
        defer { NotificationCenter.default.removeObserver(observer) }

        adapter.synchronize(textView)
        XCTAssertEqual(edits.count, 0, "An equal redraw without PII must not edit attachment text storage")
        let decoration = NativeComposerPIIDecoration(id: "email", range: NSRange(location: 0, length: 5))
        adapter.updatePIIDecorations([decoration], onExclude: { _ in })
        adapter.synchronize(textView)
        let warning = UIColor(Color.warning).withAlphaComponent(0.35)
        XCTAssertEqual(textView.textStorage.attribute(.backgroundColor, at: 0, effectiveRange: nil) as? UIColor, warning)
        edits.count = 0
        adapter.synchronize(textView)
        XCTAssertEqual(edits.count, 0, "A focus redraw with unchanged PII must preserve TextKit attachment hosts")

        adapter.updatePIIDecorations([], onExclude: { _ in })
        adapter.synchronize(textView)
        XCTAssertGreaterThan(edits.count, 0, "An actual PII change must update text storage")
        XCTAssertNil(textView.textStorage.attribute(.backgroundColor, at: 0, effectiveRange: nil))

        adapter.updatePIIDecorations([decoration], onExclude: { _ in })
        adapter.synchronize(textView)
        try controller.updateEmbed(id: "recording", status: "finished")
        adapter.synchronize(textView)
        XCTAssertEqual(textView.textStorage.attribute(.backgroundColor, at: 0, effectiveRange: nil) as? UIColor, warning,
                       "Equal-text attachment re-projection must restore PII highlights")
        try controller.loadDocument(ComposerDocumentV1(version: 1, nodes: [.text(id: "changed", source: "Other input")]))
        adapter.synchronize(textView)
        XCTAssertEqual(textView.textStorage.attribute(.backgroundColor, at: 0, effectiveRange: nil) as? UIColor, warning,
                       "Changed text must restore the current PII decoration ranges")
        adapter.updatePIIDecorations([], onExclude: { _ in })
        adapter.synchronize(textView)
        XCTAssertNil(textView.textStorage.attribute(.backgroundColor, at: 0, effectiveRange: nil))
    }

    // contract-test: supporting surface=gui.apple assertions=message-input.privacy-context
    func testPIIDecorationsUseWarningBackgroundAndExcludeOnlyTappedIdentity() throws {
        let controller = try NativeComposerController(
            document: ComposerDocumentV1(version: 1, nodes: [.text(id: "text-1", source: "alice@example.com and +49 170 1234567")]),
            selection: NSRange(location: 0, length: 0)
        )
        let adapter = makeAdapter(controller: controller)
        let textView = adapter.makePlatformView()
        let matches = PIIDetector.detect(in: controller.attributedString.string)
        var excludedIDs: [String] = []

        adapter.updatePIIDecorations(
            matches.map { .init(id: $0.id, range: $0.range) },
            onExclude: { excludedIDs.append($0) }
        )
        adapter.synchronize(textView)

        let first = try XCTUnwrap(matches.first)
        XCTAssertEqual(
            textView.attributedText.attribute(.backgroundColor, at: first.range.location, effectiveRange: nil) as? UIColor,
            UIColor(Color.warning).withAlphaComponent(0.35)
        )
        XCTAssertTrue(adapter.excludePII(atUTF16Offset: first.range.location))
        XCTAssertEqual(excludedIDs, [first.id])
    }

    // contract-test: supporting surface=gui.apple assertions=sync.surface.semantic-parity
    func testPIITapHandlingDoesNotCompeteWithEditorFocusAndSelection() throws {
        let controller = try NativeComposerController(
            document: ComposerDocumentV1(version: 1, nodes: [.text(id: "text-1", source: "alice@example.com")]),
            selection: NSRange(location: 0, length: 0)
        )
        let adapter = makeAdapter(controller: controller)
        let textView = adapter.makePlatformView()
        let exclusionTap = try XCTUnwrap(textView.gestureRecognizers?.first { $0.delegate === adapter })
        XCTAssertFalse(exclusionTap.isEnabled, "Ordinary editor taps must not enter highlight handling")
        adapter.updatePIIDecorations([.init(id: "email", range: NSRange(location: 0, length: 17))], onExclude: { _ in })
        XCTAssertTrue(exclusionTap.isEnabled)
        XCTAssertTrue(adapter.gestureRecognizer(exclusionTap, shouldRecognizeSimultaneouslyWith: UITapGestureRecognizer()))
        adapter.updatePIIDecorations([], onExclude: { _ in })
        XCTAssertFalse(exclusionTap.isEnabled)
    }
    #endif

    private func makeAdapter(
        controller: NativeComposerController,
        recorder: AccessibilityActionRecorder = AccessibilityActionRecorder(),
        accessibilityStrategy: NativeComposerAccessibilityStrategy = .syntheticDescriptors
    ) -> NativeComposerTextView {
        NativeComposerTextView(
            controller: controller,
            accessibilityLabel: "Synthetic message input",
            accessibilityHint: "Synthetic editing hint",
            embedAccessibilityLabel: { node in
                "\(node.display?.title ?? "Synthetic attachment"), \(node.status ?? "unknown")"
            },
            embedAccessibilityActions: { node in
                [(
                    name: "Synthetic remove",
                    handler: {
                        recorder.nodeIDs.append(node.id)
                        return true
                    }
                    )]
            },
            onCanonicalMarkdownChange: { _ in },
            onFocusChange: { _ in },
            onSubmit: { },
            accessibilityStrategy: accessibilityStrategy
        )
    }

    private func makeController() throws -> NativeComposerController {
        try NativeComposerController(
            document: ComposerDocumentV1(version: 1, nodes: [
                .text(id: "composer:text:before", source: "A"),
                fixtureEmbed(
                    id: "composer:embed:first",
                    title: "Synthetic image",
                    embedType: "image"
                ),
                .text(id: "composer:text:middle", source: "B"),
                fixtureEmbed(
                    id: "composer:embed:second",
                    title: "Synthetic PDF",
                    embedType: "pdf"
                ),
                .text(id: "composer:text:after", source: "C"),
            ]),
            selection: NSRange(location: 3, length: 0)
        )
    }

    private func fixtureEmbed(
        id: String,
        title: String,
        embedType: String
    ) -> ComposerNodeV1 {
        ComposerNodeV1.embed(
            id: id,
            embedType: embedType,
            canonicalSource: "```json\n{\"type\":\"\(embedType)\",\"embed_id\":\"\(id)\"}\n```",
            referenceOnly: false,
            display: ComposerEmbedDisplayV1(title: title, mediaKind: embedType),
            contentRef: "embed:\(id)"
        )
    }
}

@MainActor
private final class AccessibilityActionRecorder {
    var nodeIDs: [String] = []
}

#if canImport(UIKit)
@MainActor
private final class TextStorageEditCounter {
    var count = 0
}
#endif
