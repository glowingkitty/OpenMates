// SwiftUI bridge for the production TextKit 2 composer surface.
// The host supplies one long-lived NativeComposerSession as document authority.
// A coordinator retains stable adapter and platform-view identities across redraws.
// Focus and canonical changes flow through the session without reparsing on edits.
// Localized accessibility and host submit behavior remain explicit inputs.
// Specification: specifications/features/message-input/specification.yml
// Assertion: message-input.layout.responsive-parity

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/enter_message/MessageInput.svelte
// CSS:     frontend/packages/ui/src/components/enter_message/MessageInput.styles.css
//          Classes: .message-field, .message-field-editor
// Tokens:  ColorTokens.generated.swift, TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import SwiftUI

#if canImport(UIKit)
import UIKit

// SwiftUI probes size before committing bounds. Only a bounded measurement can
// change overflow, and the latest valid result supersedes any queued result.
@MainActor
final class NativeComposerOverflowPublication {
    typealias Scheduler = (@escaping @MainActor () -> Void) -> Void
    private let schedule: Scheduler
    private var pendingValue: Bool?
    private var pendingBinding: Binding<Bool>?
    private var scheduled = false

    init(schedule: @escaping Scheduler = { operation in DispatchQueue.main.async(execute: operation) }) {
        self.schedule = schedule
    }

    static func accepts(width: CGFloat) -> Bool {
        width.isFinite && width > 0 && width < .greatestFiniteMagnitude
    }

    func submit(_ measurement: Bool?, to binding: Binding<Bool>) {
        guard let measurement else { return }
        // Update first: an equal-to-current true must cancel an already queued
        // false. Checking binding equality before this point loses that correction.
        pendingValue = measurement
        pendingBinding = binding
        guard !scheduled else { return }
        guard binding.wrappedValue != measurement else {
            pendingValue = nil
            pendingBinding = nil
            return
        }
        scheduled = true
        schedule { [weak self] in
            guard let self else { return }
            self.scheduled = false
            guard let value = self.pendingValue, let binding = self.pendingBinding else { return }
            self.pendingValue = nil
            self.pendingBinding = nil
            if binding.wrappedValue != value { binding.wrappedValue = value }
        }
    }
}

// One real UIKit interaction/accessibility owner beside the native editor.
// Artwork remains the same web SVG/gradient; its hosting view owns no hit target.
struct NativeComposerFullscreenButton: UIViewRepresentable {
    let fullscreen: Bool
    let action: () -> Void

    func makeUIView(context: Context) -> NativeComposerFullscreenUIKitButton {
        NativeComposerFullscreenUIKitButton()
    }

    func updateUIView(_ button: NativeComposerFullscreenUIKitButton, context: Context) {
        button.onPress = action
        #if DEBUG
        button.diagnosticUpdateCount += 1
        #endif
        button.accessibilityIdentifier = "message-input-fullscreen-button"
        button.accessibilityLabel = fullscreen ? AppStrings.exitFullscreen : AppStrings.enterFullscreen
        button.artwork.rootView = NativeComposerFullscreenArtwork(fullscreen: fullscreen)
    }

    func sizeThatFits(_ proposal: ProposedViewSize,
        uiView: NativeComposerFullscreenUIKitButton, context: Context) -> CGSize? {
        CGSize(width: MessageComposerMetric.expandControlSize, height: MessageComposerMetric.expandControlSize)
    }
}

struct NativeComposerFullscreenArtwork: View {
    let fullscreen: Bool
    var body: some View {
        Icon(fullscreen ? "minimize" : "fullscreen", size: 20)
            .foregroundStyle(LinearGradient.primary)
            .frame(width: 30, height: 30)
            .allowsHitTesting(false)
            .accessibilityHidden(true)
    }
}

final class NativeComposerFullscreenUIKitButton: UIButton {
    let artwork = UIHostingController(rootView: NativeComposerFullscreenArtwork(fullscreen: false))
    var onPress: () -> Void = { }
    #if DEBUG
    var diagnosticUpdateCount = 0
    private var diagnosticLayoutCount = 0
    private var diagnosticWindowMoveCount = 0

    // Synthetic-fixture geometry only; no labels, draft, account or content.
    // Computed on demand without timers or observable/global publication.
    var diagnosticGeometry: [String: Any] {
        func rect(_ value: CGRect) -> [Any] {
            [value.minX, value.minY, value.width, value.height].map {
                $0.isFinite ? NSNumber(value: Double($0)) : "nonfinite" as Any
            }
        }
        var parents: [[String: Any]] = []
        var ancestor: UIView? = self
        for _ in 0..<10 {
            guard let view = ancestor else { break }
            parents.append(["class": String(describing: type(of: view)),
                "frame": rect(view.frame), "bounds": rect(view.bounds),
                "hidden": view.isHidden, "alpha": view.alpha,
                "clips": view.clipsToBounds, "axElement": view.isAccessibilityElement,
                "axChildrenHidden": view.accessibilityElementsHidden])
            ancestor = view.superview
        }
        let points = [CGPoint(x: bounds.midX, y: bounds.midY),
            CGPoint(x: 1, y: 1), CGPoint(x: bounds.width - 1, y: bounds.height - 1)]
        let hitOwners: [[String: Any]] = points.map { point in
            let hit = window?.hitTest(convert(point, to: window), with: nil)
            return ["class": hit.map { String(describing: type(of: $0)) } ?? "none",
                "ownsButton": hit === self, "point": [point.x, point.y]]
        }
        return ["hitOwners": hitOwners, "frame": rect(frame), "bounds": rect(bounds),
            "viewport": rect(convert(bounds, to: window)),
            "axFrame": rect(accessibilityFrame), "windowAttached": window != nil,
            "updates": diagnosticUpdateCount, "layouts": diagnosticLayoutCount,
            "windowMoves": diagnosticWindowMoveCount, "parents": parents]
    }

    // Changing counters belong only to on-demand reads, never the bound
    // field value: publishing them would itself drive another SwiftUI update.
    var boundDiagnosticGeometry: [String: Any] {
        diagnosticGeometry.filter { !["updates", "layouts", "windowMoves"].contains($0.key) }
    }

    override var accessibilityValue: String? {
        get {
            guard ProcessInfo.processInfo.arguments.contains("--ui-test-composer-control-diagnostics"),
                  let data = try? JSONSerialization.data(withJSONObject: diagnosticGeometry, options: [.sortedKeys]) else {
                return super.accessibilityValue
            }
            return String(data: data, encoding: .utf8)
        }
        set { super.accessibilityValue = newValue }
    }

    override func didMoveToWindow() {
        super.didMoveToWindow()
        diagnosticWindowMoveCount += 1
    }
    #endif

    init() {
        super.init(frame: CGRect(origin: .zero, size: CGSize(
            width: MessageComposerMetric.expandControlSize, height: MessageComposerMetric.expandControlSize)))
        backgroundColor = .clear
        isAccessibilityElement = true
        accessibilityTraits = .button
        artwork.view.backgroundColor = .clear
        artwork.view.isUserInteractionEnabled = false
        artwork.view.accessibilityElementsHidden = true
        addSubview(artwork.view)
        addTarget(self, action: #selector(press), for: .touchUpInside)
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override var intrinsicContentSize: CGSize {
        CGSize(width: MessageComposerMetric.expandControlSize, height: MessageComposerMetric.expandControlSize)
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        #if DEBUG
        diagnosticLayoutCount += 1
        #endif
        artwork.view.frame = CGRect(x: (bounds.width - 30) / 2,
            y: (bounds.height - 30) / 2, width: 30, height: 30)
    }

    @objc private func press() { onPress() }
}

struct NativeComposerEditorView: UIViewRepresentable {
    @ObservedObject var session: NativeComposerSession
    let isFocused: Binding<Bool>
    let isEditable: Bool
    let accessibilityHint: String
    var measuredHeight: Binding<CGFloat> = .constant(0)
    var topFadeActive: Binding<Bool> = .constant(false)
    var reservesControlLane = false
    var layoutDiagnostic: Binding<String> = .constant("")
    var maximumUnscrolledHeight: CGFloat = .greatestFiniteMagnitude
    var contentOverflows: Binding<Bool> = .constant(false)
    var piiDecorations: [NativeComposerPIIDecoration] = []
    var onExcludePII: (String) -> Void = { _ in }
    let onSubmit: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(session: session, accessibilityHint: accessibilityHint)
    }

    func makeUIView(context: Context) -> UITextView {
        let textView = context.coordinator.adapter.makePlatformView()
        textView.backgroundColor = .clear
        textView.isScrollEnabled = true
        textView.showsVerticalScrollIndicator = false
        textView.textContainerInset = UIEdgeInsets(
            top: MessageComposerMetric.editorVerticalInset,
            left: .spacing6,
            bottom: MessageComposerMetric.editorVerticalInset,
            right: .spacing6
        )
        context.coordinator.onLayoutDiagnostic = publishLayoutDiagnostic
        context.coordinator.reservesControlLane = reservesControlLane
        context.coordinator.applyControlLane(to: textView)
        context.coordinator.installScrollFade(on: textView)
        return textView
    }

    func sizeThatFits(_ proposal: ProposedViewSize, uiView: UITextView, context: Context) -> CGSize? {
        guard let width = proposal.width else { return nil }
        context.coordinator.reservesControlLane = reservesControlLane
        context.coordinator.applyControlLane(to: uiView)
        let proposedOverflow = context.coordinator.overflowMeasurement(uiView, width: width, limit: maximumUnscrolledHeight)
        #if DEBUG
        context.coordinator.recordOverflowProbe(uiView, stage: "proposal", width: width,
            limit: maximumUnscrolledHeight, result: proposedOverflow)
        #endif
        context.coordinator.publishOverflow(proposedOverflow, to: contentOverflows)
        let intrinsic = resolvedHeight(for: uiView, width: width)
        // The field proposes its bounded editor lane, not a shell around a short
        // intrinsic text view. Keep intrinsic measurement independent for collapse.
        let height = proposal.height.flatMap { $0.isFinite ? max(0, $0) : nil } ?? intrinsic
        return CGSize(width: width, height: height)
    }

    func updateUIView(_ textView: UITextView, context: Context) {
        context.coordinator.onFadeChange = publishTopFade
        context.coordinator.onLayoutDiagnostic = publishLayoutDiagnostic
        context.coordinator.reservesControlLane = reservesControlLane
        context.coordinator.applyControlLane(to: textView)
        context.coordinator.updateScrollFade(textView)
        context.coordinator.onFocusChange = { isFocused.wrappedValue = $0 }
        context.coordinator.onSubmit = onSubmit
        context.coordinator.adapter.updatePIIDecorations(piiDecorations, onExclude: onExcludePII)
        context.coordinator.adapter.synchronize(textView)
        let nativeOverflow = context.coordinator.overflowMeasurement(textView, width: textView.bounds.width, limit: maximumUnscrolledHeight)
        #if DEBUG
        context.coordinator.recordOverflowProbe(textView, stage: "native", width: textView.bounds.width,
            limit: maximumUnscrolledHeight, result: nativeOverflow)
        #endif
        context.coordinator.publishOverflow(nativeOverflow, to: contentOverflows)
        context.coordinator.updateScrollFade(textView)
        textView.isEditable = isEditable
        if textView.bounds.width > 0 {
            publishMeasuredHeight(resolvedHeight(for: textView, width: textView.bounds.width))
        }
        if isFocused.wrappedValue, !textView.isFirstResponder {
            textView.becomeFirstResponder()
        } else if !isFocused.wrappedValue, textView.isFirstResponder {
            textView.resignFirstResponder()
        }
    }

    private func resolvedHeight(for textView: UITextView, width: CGFloat) -> CGFloat {
        let contentSize = textView.sizeThatFits(
            CGSize(width: width, height: .greatestFiniteMagnitude)
        )
        let containsEmbed = session.controller.document.nodes.contains(where: { $0.kind == "embed" })
        return MessageComposerMetric.editorHeight(
            for: contentSize.height,
            containsEmbed: containsEmbed
        )
    }

    private func publishLayoutDiagnostic(_ value: String) {
        #if DEBUG
        guard layoutDiagnostic.wrappedValue != value else { return }
        DispatchQueue.main.async {
            guard layoutDiagnostic.wrappedValue != value else { return }
            layoutDiagnostic.wrappedValue = value
        }
        #endif
    }

    private func publishTopFade(_ active: Bool) {
        guard topFadeActive.wrappedValue != active else { return }
        DispatchQueue.main.async {
            guard topFadeActive.wrappedValue != active else { return }
            topFadeActive.wrappedValue = active
        }
    }

    private func publishMeasuredHeight(_ height: CGFloat) {
        guard abs(measuredHeight.wrappedValue - height) > 0.5 else { return }
        DispatchQueue.main.async {
            measuredHeight.wrappedValue = height
        }
    }

    static func dismantleUIView(_ uiView: UITextView, coordinator: Coordinator) {
        coordinator.boundsObservation?.invalidate()
        coordinator.boundsObservation = nil
        coordinator.adapter.onScroll = { _ in }
        uiView.layer.mask = nil
    }

    @MainActor
    final class Coordinator {
        var boundsObservation: NSKeyValueObservation?
        var onFadeChange: (Bool) -> Void = { _ in }
        private let fadeMask = CAGradientLayer()
        var reservesControlLane = false
        var onLayoutDiagnostic: (String) -> Void = { _ in }
        private var lastLayoutDiagnostic: String?
        private let overflowCache = NativeComposerOverflowCache()
        private let overflowPublication = NativeComposerOverflowPublication()

        func overflowMeasurement(_ view: UITextView, width: CGFloat, limit: CGFloat) -> Bool? {
            guard NativeComposerOverflowPublication.accepts(width: width) else {
                #if DEBUG
                lastOverflowMeasurement = ["unmeasuredWidth": true]
                #endif
                return nil
            }
            return measuredOverflow(view, width: width, limit: limit)
        }

        func publishOverflow(_ measurement: Bool?, to binding: Binding<Bool>) {
            overflowPublication.submit(measurement, to: binding)
        }
        #if DEBUG
        private var overflowProbeHistory: [[String: Any]] = []
        private var lastOverflowMeasurement: [String: Any] = [:]

        func recordOverflowProbe(_ view: UITextView, stage: String,
            width: CGFloat, limit: CGFloat, result: Bool?) {
            guard ProcessInfo.processInfo.arguments.contains("--ui-test-composer-control-diagnostics") else { return }
            func number(_ value: CGFloat) -> Any {
                value.isFinite ? NSNumber(value: Double(value)) : "nonfinite" as Any
            }
            var entry = lastOverflowMeasurement
            entry["stage"] = stage
            entry["width"] = number(width)
            entry["limit"] = number(limit)
            entry["actualWidth"] = number(view.bounds.width)
            entry["actualHeight"] = number(view.bounds.height)
            entry["rightInset"] = number(view.textContainerInset.right)
            entry["reservesLane"] = reservesControlLane
            entry["measurementValid"] = result != nil
            if let result { entry["result"] = result }
            else { entry["result"] = "unmeasured" }
            // Proposal/native provenance and cache hits are useful evidence,
            // but do not make an otherwise identical geometry/result a change.
            let incidental = ["stage", "cached", "measuredHeight", "compensation"]
            let state = entry.filter { !incidental.contains($0.key) }
            if let previous = overflowProbeHistory.last {
                let previousState = previous.filter { !incidental.contains($0.key) }
                if NSDictionary(dictionary: state).isEqual(to: previousState) { return }
            }
            overflowProbeHistory.append(entry)
            if overflowProbeHistory.count > 16 { overflowProbeHistory.removeFirst() }
        }
        #endif

        func measuredOverflow(_ view: UITextView, width: CGFloat, limit: CGFloat) -> Bool {
            guard width > 0, view.textStorage.length > 0 else {
                #if DEBUG
                lastOverflowMeasurement = ["invalidWidth": width <= 0, "empty": view.textStorage.length == 0]
                #endif
                return false
            }
            let key = overflowCache.key(revision: adapter.synchronizedRevision, storage: view.textStorage,
                width: width, limit: limit, linePadding: view.textContainer.lineFragmentPadding)
            if let value = overflowCache.value(for: key) {
                #if DEBUG
                lastOverflowMeasurement = ["cached": true]
                #endif
                return value
            }
            // Proposed-width compensation measures the SAME native view at its
            // full physical width without modifying live insets/bounds/selection.
            let compensation = view.textContainerInset.right - MessageComposerMetric.editorHorizontalInset
            let height = view.sizeThatFits(CGSize(width: width + compensation, height: .greatestFiniteMagnitude)).height
            #if DEBUG
            lastOverflowMeasurement = ["cached": false,
                "measuredHeight": height.isFinite ? NSNumber(value: Double(height)) : "nonfinite" as Any,
                "compensation": compensation]
            #endif
            return overflowCache.store(height > limit + 1, for: key)
        }

        func applyControlLane(to textView: UITextView) {
            let right = reservesControlLane ? MessageComposerMetric.plaintextControlRightInset
                : MessageComposerMetric.editorHorizontalInset
            guard textView.textContainerInset.right != right else { return }
            var inset = textView.textContainerInset; inset.right = right
            textView.textContainerInset = inset
        }

        func installScrollFade(on textView: UITextView) {
            adapter.onScroll = { [weak self] scrollView in
                guard let textView = scrollView as? UITextView else { return }
                self?.updateScrollFade(textView)
            }
            boundsObservation = textView.observe(\.bounds, options: [.new]) { [weak self] textView, _ in
                MainActor.assumeIsolated { self?.updateScrollFade(textView) }
            }
            updateScrollFade(textView)
        }

        func updateScrollFade(_ textView: UITextView) {
            let active = textView.contentOffset.y + textView.adjustedContentInset.top > 0.5
                && textView.bounds.height > 0
                && textView.contentSize.height + textView.adjustedContentInset.top + textView.adjustedContentInset.bottom > textView.bounds.height + 0.5
            CATransaction.begin(); CATransaction.setDisableActions(true)
            if active {
                fadeMask.frame = textView.bounds
                fadeMask.colors = [UIColor.clear.cgColor, UIColor.black.cgColor, UIColor.black.cgColor]
                fadeMask.locations = [0, NSNumber(value: Double(min(1, CGFloat.spacing6 / textView.bounds.height))), 1]
                textView.layer.mask = fadeMask
            } else { textView.layer.mask = nil }
            CATransaction.commit()
            onFadeChange(active)
            #if DEBUG
            // Native caret/text-container geometry only; no text/draft is exposed.
            if textView.window != nil {
                let position = textView.closestPosition(to: CGPoint(x: textView.textContainerInset.left + textView.textContainer.lineFragmentPadding,
                    // The text inset belongs to the document, not each scroll
                    // viewport. Adding it again after scrolling skips the real
                    // partially visible first row beside the sticky control.
                    y: max(textView.bounds.minY, textView.textContainerInset.top))) ?? textView.beginningOfDocument
                let first = textView.caretRect(for: position)
                let selected = textView.caretRect(for: textView.selectedTextRange?.end ?? textView.beginningOfDocument)
                let right = textView.bounds.maxX - textView.textContainerInset.right - textView.textContainer.lineFragmentPadding
                let viewport = textView.convert(textView.bounds, to: textView.window)
                var payload: [String: Any] = ["viewport": [viewport.minX, viewport.minY, viewport.width, viewport.height],
                    "first": [first.minX, first.minY, first.width, first.height],
                    "selected": [selected.minX, selected.minY, selected.width, selected.height],
                    "right": right, "offset": textView.contentOffset.y,
                    "bounds": [textView.bounds.minX, textView.bounds.minY, textView.bounds.width, textView.bounds.height]]
                if ProcessInfo.processInfo.arguments.contains("--ui-test-composer-control-diagnostics"),
                   let window = textView.window {
                    var remaining: [UIView] = [window]
                    var visited = 0
                    var controls: [[String: Any]] = []
                    // Bound traversal; only this dedicated control's numerical
                    // geometry enters the existing synthetic field diagnostic.
                    while let view = remaining.popLast(), visited < 1024 {
                        visited += 1
                        if let control = view as? NativeComposerFullscreenUIKitButton {
                            controls.append(control.boundDiagnosticGeometry)
                        }
                        remaining.append(contentsOf: view.subviews)
                    }
                    payload["overflowProbes"] = overflowProbeHistory
                    payload["fullscreenControls"] = controls
                    payload["controlProbeVisited"] = visited
                    payload["controlProbeTruncated"] = !remaining.isEmpty
                }
                if let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]),
                   let value = String(data: data, encoding: .utf8), value != lastLayoutDiagnostic {
                    lastLayoutDiagnostic = value; onLayoutDiagnostic(value)
                }
            }
            #endif
        }
        let adapter: NativeComposerTextView
        var onFocusChange: (Bool) -> Void = { _ in }
        var onSubmit: () -> Void = { }

        init(session: NativeComposerSession, accessibilityHint: String) {
            adapter = NativeComposerTextView(
                controller: session.controller,
                accessibilityLabel: AppStrings.chatMessageInput,
                accessibilityHint: accessibilityHint,
                embedAccessibilityLabel: { node in node.display?.title ?? node.embedType ?? "" },
                embedAccessibilityActions: { _ in [] },
                onCanonicalMarkdownChange: { [weak session] markdown in
                    session?.publishControllerState(canonicalMarkdown: markdown)
                },
                onFocusChange: { _ in },
                onSubmit: { },
                accessibilityStrategy: .hostedAttachments
            )
            adapter.onFocusChange = { [weak self] focused in self?.onFocusChange(focused) }
            adapter.onSubmit = { [weak self] in self?.onSubmit() }
        }
    }
}
#elseif canImport(AppKit)
import AppKit

struct NativeComposerEditorView: NSViewRepresentable {
    @ObservedObject var session: NativeComposerSession
    let isFocused: Binding<Bool>
    let isEditable: Bool
    let accessibilityHint: String
    var measuredHeight: Binding<CGFloat> = .constant(0)
    var topFadeActive: Binding<Bool> = .constant(false)
    var reservesControlLane = false
    var layoutDiagnostic: Binding<String> = .constant("")
    var maximumUnscrolledHeight: CGFloat = .greatestFiniteMagnitude
    var contentOverflows: Binding<Bool> = .constant(false)
    var piiDecorations: [NativeComposerPIIDecoration] = []
    var onExcludePII: (String) -> Void = { _ in }
    let onSubmit: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(session: session, accessibilityHint: accessibilityHint)
    }

    func makeNSView(context: Context) -> NSScrollView {
        let textView = context.coordinator.adapter.makePlatformView()
        textView.drawsBackground = false
        textView.isSelectable = isFocused.wrappedValue
        textView.isEditable = isEditable && isFocused.wrappedValue
        textView.addGestureRecognizer(NSClickGestureRecognizer(
            target: context.coordinator,
            action: #selector(Coordinator.focusEditorFromClick)
        ))
        textView.textContainerInset = NSSize(
            width: .spacing6,
            height: MessageComposerMetric.editorVerticalInset
        )
        textView.isVerticallyResizable = true
        textView.isHorizontallyResizable = false
        textView.textContainer?.widthTracksTextView = true
        textView.textContainer?.heightTracksTextView = false
        let scrollView = NSScrollView()
        scrollView.drawsBackground = false
        scrollView.hasVerticalScroller = false
        scrollView.documentView = textView
        context.coordinator.reservesControlLane = reservesControlLane
        context.coordinator.installScrollFade(on: scrollView)
        // AppKit may choose the first editable view when this scroll view joins a
        // window, after the first SwiftUI update has already run.
        Task { @MainActor [weak scrollView] in
            guard let textView = scrollView?.documentView as? NSTextView,
                  let window = textView.window else { return }
            if isFocused.wrappedValue {
                if window.firstResponder !== textView {
                    window.makeFirstResponder(textView)
                }
            } else if window.firstResponder === textView {
                window.makeFirstResponder(nil)
            }
        }
        return scrollView
    }

    func sizeThatFits(_ proposal: ProposedViewSize, nsView: NSScrollView, context: Context) -> CGSize? {
        guard let width = proposal.width else { return nil }
        context.coordinator.reservesControlLane = reservesControlLane
        if let textView = nsView.documentView as? NSTextView {
            context.coordinator.applyControlLane(to: textView, width: width)
        }
        if let textView = nsView.documentView as? NSTextView {
            publishOverflow(context.coordinator.measuredOverflow(textView, width: width, limit: maximumUnscrolledHeight))
        }
        let intrinsic = resolvedHeight(for: nsView, width: width)
        // The field proposes its bounded editor lane, not a shell around a short
        // intrinsic text view. Keep intrinsic measurement independent for collapse.
        let height = proposal.height.flatMap { $0.isFinite ? max(0, $0) : nil } ?? intrinsic
        context.coordinator.viewportHeight = height
        if let textView = nsView.documentView as? NSTextView, textView.frame.height < height {
            textView.setFrameSize(NSSize(width: width, height: height))
        }
        return CGSize(width: width, height: height)
    }

    func updateNSView(_ scrollView: NSScrollView, context: Context) {
        guard let textView = scrollView.documentView as? NSTextView else { return }
        context.coordinator.onFadeChange = publishTopFade
        context.coordinator.reservesControlLane = reservesControlLane
        context.coordinator.applyControlLane(to: textView, width: scrollView.bounds.width)
        context.coordinator.updateScrollFade(scrollView)
        context.coordinator.onFocusChange = { isFocused.wrappedValue = $0 }
        context.coordinator.onSubmit = onSubmit
        context.coordinator.adapter.synchronize(textView)
        publishOverflow(context.coordinator.measuredOverflow(textView, width: scrollView.bounds.width, limit: maximumUnscrolledHeight))
        // AppKit can make an editable text view first responder when a window
        // opens. Keep the idle editor out of that selection until the composer
        // host receives a click and sets its focus binding.
        textView.isSelectable = isFocused.wrappedValue
        textView.isEditable = isEditable && isFocused.wrappedValue
        if scrollView.bounds.width > 0 {
            publishMeasuredHeight(resolvedHeight(for: scrollView, width: scrollView.bounds.width))
            if let viewport = context.coordinator.viewportHeight, textView.frame.height < viewport {
                textView.setFrameSize(NSSize(width: textView.frame.width, height: viewport))
            }
        }
        if let window = textView.window {
            if isFocused.wrappedValue {
                if window.firstResponder !== textView {
                    window.makeFirstResponder(textView)
                }
            } else if window.firstResponder === textView {
                window.makeFirstResponder(nil)
            }
        }
    }

    private func resolvedHeight(for scrollView: NSScrollView, width: CGFloat) -> CGFloat {
        guard let textView = scrollView.documentView as? NSTextView else { return 0 }
        let editorWidth = max(1, width)
        if abs(textView.frame.width - editorWidth) > 0.5 {
            textView.setFrameSize(NSSize(width: editorWidth, height: max(1, textView.frame.height)))
        }
        if let layoutManager = textView.textLayoutManager,
           let documentRange = textView.textContentStorage?.documentRange {
            layoutManager.ensureLayout(for: documentRange)
        }
        let lineHeight = textView.textLayoutManager?.usageBoundsForTextContainer.height ?? 0
        let contentHeight = max(MessageComposerMetric.editorLineHeight, lineHeight)
            + (textView.textContainerInset.height * 2)
        if abs(textView.frame.height - contentHeight) > 0.5 {
            textView.setFrameSize(NSSize(width: editorWidth, height: contentHeight))
        }
        let containsEmbed = session.controller.document.nodes.contains { $0.kind == "embed" }
        return MessageComposerMetric.editorHeight(for: contentHeight, containsEmbed: containsEmbed)
    }

    private func publishOverflow(_ value: Bool) {
        guard contentOverflows.wrappedValue != value else { return }
        DispatchQueue.main.async {
            guard contentOverflows.wrappedValue != value else { return }
            contentOverflows.wrappedValue = value
        }
    }

    private func publishLayoutDiagnostic(_ value: String) {
        #if DEBUG
        guard layoutDiagnostic.wrappedValue != value else { return }
        DispatchQueue.main.async {
            guard layoutDiagnostic.wrappedValue != value else { return }
            layoutDiagnostic.wrappedValue = value
        }
        #endif
    }

    private func publishTopFade(_ active: Bool) {
        guard topFadeActive.wrappedValue != active else { return }
        DispatchQueue.main.async {
            guard topFadeActive.wrappedValue != active else { return }
            topFadeActive.wrappedValue = active
        }
    }

    private func publishMeasuredHeight(_ height: CGFloat) {
        guard abs(measuredHeight.wrappedValue - height) > 0.5 else { return }
        DispatchQueue.main.async {
            guard abs(measuredHeight.wrappedValue - height) > 0.5 else { return }
            measuredHeight.wrappedValue = height
        }
    }

    static func dismantleNSView(_ nsView: NSScrollView, coordinator: Coordinator) {
        if let observer = coordinator.boundsObserver { NotificationCenter.default.removeObserver(observer) }
        coordinator.boundsObserver = nil
        nsView.contentView.layer?.mask = nil
    }

    @MainActor
    final class Coordinator: NSObject {
        var boundsObserver: NSObjectProtocol?
        var onFadeChange: (Bool) -> Void = { _ in }
        private let fadeMask = CAGradientLayer()
        var reservesControlLane = false
        private let overflowCache = NativeComposerOverflowCache()

        func measuredOverflow(_ view: NSTextView, width: CGFloat, limit: CGFloat) -> Bool {
            guard width > 0, let storage = view.textStorage, storage.length > 0 else { return false }
            let padding = view.textContainer?.lineFragmentPadding ?? 5
            let key = overflowCache.key(revision: adapter.synchronizedRevision, storage: storage,
                width: width, limit: limit, linePadding: padding)
            if let value = overflowCache.value(for: key) { return value }
            // Detached sizing uses native attributed runs and geometry-only
            // attachments. It never makes a UI provider or mutates the live view.
            let copy = NSMutableAttributedString(attributedString: storage)
            let containerWidth = max(1, width - view.textContainerInset.width - MessageComposerMetric.editorHorizontalInset)
            var replacements: [(NSRange, NSTextAttachment)] = []
            storage.enumerateAttribute(.attachment, in: NSRange(location: 0, length: storage.length)) { value, range, _ in
                guard let attachment = value as? NSTextAttachment else { return }
                let geometry = NSTextAttachment()
                geometry.bounds = ComposerAttachmentViewProvider.measurementBounds(for: attachment,
                    availableWidth: max(1, containerWidth - padding * 2))
                replacements.append((range, geometry))
            }
            for (range, geometry) in replacements { copy.addAttribute(.attachment, value: geometry, range: range) }
            let content = NSTextContentStorage(); content.attributedString = copy
            let layout = NSTextLayoutManager(); content.addTextLayoutManager(layout)
            let container = NSTextContainer(size: CGSize(width: containerWidth, height: .greatestFiniteMagnitude))
            container.lineFragmentPadding = padding; layout.textContainer = container
            layout.ensureLayout(for: content.documentRange)
            let height = max(MessageComposerMetric.editorLineHeight, layout.usageBoundsForTextContainer.height)
                + view.textContainerInset.height * 2
            return overflowCache.store(height > limit + 1, for: key)
        }

        func applyControlLane(to textView: NSTextView, width: CGFloat) {
            guard width > 0, let container = textView.textContainer else { return }
            let right = reservesControlLane ? MessageComposerMetric.plaintextControlRightInset
                : MessageComposerMetric.editorHorizontalInset
            let available = max(1, width - textView.textContainerInset.width - right)
            container.widthTracksTextView = false
            if abs(container.size.width - available) > 0.5 {
                container.size = NSSize(width: available, height: .greatestFiniteMagnitude)
            }
        }

        func installScrollFade(on scrollView: NSScrollView) {
            let clipView = scrollView.contentView
            clipView.wantsLayer = true
            clipView.postsBoundsChangedNotifications = true
            boundsObserver = NotificationCenter.default.addObserver(
                forName: NSView.boundsDidChangeNotification, object: clipView, queue: .main
            ) { [weak self, weak scrollView] _ in
                MainActor.assumeIsolated {
                    if let scrollView { self?.updateScrollFade(scrollView) }
                }
            }
            updateScrollFade(scrollView)
        }

        func updateScrollFade(_ scrollView: NSScrollView) {
            let clipView = scrollView.contentView
            let active = clipView.bounds.minY > 0.5 && clipView.bounds.height > 0
                && (scrollView.documentView?.bounds.height ?? 0) > clipView.bounds.height + 0.5
            CATransaction.begin(); CATransaction.setDisableActions(true)
            if active, let layer = clipView.layer {
                fadeMask.frame = layer.bounds
                // Layer orientation follows the actual native clip view.
                fadeMask.startPoint = CGPoint(x: 0.5, y: clipView.isFlipped ? 0 : 1)
                fadeMask.endPoint = CGPoint(x: 0.5, y: clipView.isFlipped ? 1 : 0)
                fadeMask.colors = [NSColor.clear.cgColor, NSColor.black.cgColor, NSColor.black.cgColor]
                fadeMask.locations = [0, NSNumber(value: Double(min(1, CGFloat.spacing6 / clipView.bounds.height))), 1]
                layer.mask = fadeMask
            } else { clipView.layer?.mask = nil }
            CATransaction.commit()
            onFadeChange(active)
        }
        var viewportHeight: CGFloat?
        let adapter: NativeComposerTextView
        var onFocusChange: (Bool) -> Void = { _ in }
        var onSubmit: () -> Void = { }

        init(session: NativeComposerSession, accessibilityHint: String) {
            adapter = NativeComposerTextView(
                controller: session.controller,
                accessibilityLabel: AppStrings.chatMessageInput,
                accessibilityHint: accessibilityHint,
                embedAccessibilityLabel: { node in node.display?.title ?? node.embedType ?? "" },
                embedAccessibilityActions: { _ in [] },
                onCanonicalMarkdownChange: { [weak session] markdown in
                    session?.publishControllerState(canonicalMarkdown: markdown)
                },
                onFocusChange: { _ in },
                onSubmit: { }
            )
            super.init()
            adapter.onFocusChange = { [weak self] focused in self?.onFocusChange(focused) }
            adapter.onSubmit = { [weak self] in self?.onSubmit() }
        }

        @objc func focusEditorFromClick() {
            onFocusChange(true)
        }
    }
}
#endif

#if canImport(UIKit) || canImport(AppKit)
@MainActor
private final class NativeComposerOverflowCache {
    struct Key: Equatable {
        let revision: Int?
        let width: CGFloat
        let limit: CGFloat
        let padding: CGFloat
        let attachments: [CGRect]
    }
    private var attachments: [NSTextAttachment] = []
    private var attachmentRevision: Int?
    private var cachedKey: Key?
    private var cachedValue = false
    func key(revision: Int?, storage: NSAttributedString, width: CGFloat, limit: CGFloat, linePadding: CGFloat) -> Key {
        if revision != attachmentRevision || cachedKey == nil {
            attachments = []
            storage.enumerateAttribute(.attachment, in: NSRange(location: 0, length: storage.length)) { value, _, _ in
                if let attachment = value as? NSTextAttachment { attachments.append(attachment) }
            }
            attachmentRevision = revision
        }
        let available = max(1, width - MessageComposerMetric.editorHorizontalInset * 2 - linePadding * 2)
        let bounds = attachments.map { ComposerAttachmentViewProvider.measurementBounds(for: $0, availableWidth: available) }
        return Key(revision: revision, width: width, limit: limit, padding: linePadding, attachments: bounds)
    }
    func value(for key: Key) -> Bool? { cachedKey == key ? cachedValue : nil }
    func store(_ value: Bool, for key: Key) -> Bool { cachedKey = key; cachedValue = value; return value }
}
#endif
