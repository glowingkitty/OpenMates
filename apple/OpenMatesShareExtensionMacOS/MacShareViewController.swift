// macOS share extension for sending URLs, text, and supported files into
// encrypted chats. This mirrors the focused iOS share flow with an AppKit host
// controller: preview shared content, add an optional instruction, choose New
// Chat or a recent chat, then send through BackgroundChatSender with embeds.
// Secrets remain in the shared Keychain access group; App Group defaults are
// used only for cached session metadata needed by extension processes.

import AppKit
import UniformTypeIdentifiers
import WebKit

@MainActor
final class MacShareViewController: NSViewController {
    private enum Layout {
        static let outerPadding: CGFloat = 18
        static let stackSpacing: CGFloat = 12
        static let buttonHeight: CGFloat = 34
        static let messageHeight: CGFloat = 112
        static let composerCornerRadius: CGFloat = 24
        static let composerBorderWidth: CGFloat = 2
        static let tableRowHeight: CGFloat = 42
        static let tableMaxVisibleRows = 5
    }

    private struct SharedPart {
        let text: String
        let isURL: Bool
    }

    private struct SharedAttachment {
        let data: Data
        let filename: String
        let contentType: String
    }

    private final class SharedPartCollector: @unchecked Sendable {
        private var parts: [SharedPart] = []
        private var attachments: [SharedAttachment] = []
        private var unsupported: [String] = []
        private let lock = NSLock()

        func append(_ part: SharedPart) {
            lock.lock()
            parts.append(part)
            lock.unlock()
        }

        func append(_ attachment: SharedAttachment) {
            lock.lock()
            attachments.append(attachment)
            lock.unlock()
        }

        func appendUnsupported(_ filename: String) {
            lock.lock()
            unsupported.append(filename)
            lock.unlock()
        }

        func values() -> [SharedPart] {
            lock.lock()
            let snapshot = parts
            lock.unlock()
            return snapshot
        }

        func attachmentValues() -> [SharedAttachment] {
            lock.lock()
            let snapshot = attachments
            lock.unlock()
            return snapshot
        }

        func unsupportedValues() -> [String] {
            lock.lock()
            let snapshot = unsupported
            lock.unlock()
            return snapshot
        }
    }

    private nonisolated static func sharedURLText(from value: Any?) -> String? {
        if let url = value as? URL {
            return url.absoluteString
        }
        if let url = value as? NSURL {
            return url.absoluteString
        }
        if let text = value as? String {
            return text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : text
        }
        if let text = value as? NSString {
            let string = text as String
            return string.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : string
        }
        return nil
    }

    private nonisolated static func sharedFileURL(from value: Any?) -> URL? {
        if let url = value as? URL { return url.isFileURL ? url : nil }
        if let url = value as? NSURL, url.isFileURL { return url as URL }
        return nil
    }

    private nonisolated static func sharedPlainText(from value: Any?) -> String? {
        if let text = value as? String {
            return text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : text
        }
        if let text = value as? NSString {
            let string = text as String
            return string.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : string
        }
        return nil
    }

    private nonisolated static func attachmentFilename(from provider: NSItemProvider, typeIdentifier: String) -> String {
        if let suggestedName = provider.suggestedName, !suggestedName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            let ext = UTType(typeIdentifier)?.preferredFilenameExtension
            if let ext, URL(fileURLWithPath: suggestedName).pathExtension.isEmpty {
                return "\(suggestedName).\(ext)"
            }
            return suggestedName
        }
        if let ext = UTType(typeIdentifier)?.preferredFilenameExtension {
            return "Shared Attachment.\(ext)"
        }
        return "Shared Attachment"
    }

    private nonisolated static func attachmentContentType(typeIdentifier: String, fallbackFilename: String) -> String {
        if let mime = UTType(typeIdentifier)?.preferredMIMEType { return mime }
        if let type = UTType(filenameExtension: URL(fileURLWithPath: fallbackFilename).pathExtension), let mime = type.preferredMIMEType {
            return mime
        }
        return "application/octet-stream"
    }

    private nonisolated static func firstSupportedAttachmentType(from provider: NSItemProvider) -> String? {
        provider.registeredTypeIdentifiers.first { identifier in
            let filename = attachmentFilename(from: provider, typeIdentifier: identifier)
            let contentType = attachmentContentType(typeIdentifier: identifier, fallbackFilename: filename)
            return BackgroundAttachmentClassifier.classification(filename: filename, contentType: contentType) != nil
        }
    }

    private nonisolated static func isAllowedAttachmentSize(_ url: URL) -> Bool {
        guard let values = try? url.resourceValues(forKeys: [.fileSizeKey]), let size = values.fileSize else {
            return false
        }
        return size <= BackgroundAttachmentClassifier.maxFileSizeBytes
    }

    private var sharedParts: [SharedPart] = []
    private var sharedAttachments: [SharedAttachment] = []
    private var unsupportedAttachments: [String] = []
    private var recentChats: [BackgroundChatSender.DestinationChat] = []
    private var selectedChat: BackgroundChatSender.DestinationChat?
    private var isSubmitting = false

    private let sender = BackgroundChatSender()
    private let rootStack = NSStackView()
    private let cancelButton = NSButton(title: "Cancel", target: nil, action: nil)
    private let sendButton = NSButton(title: "Send", target: nil, action: nil)
    private let previewLabel = NSTextField(labelWithString: "")
    private let messageComposerView = NSView()
    private let messageFieldView = NSView()
    private lazy var messageEditorWebView: WKWebView = {
        let contentController = WKUserContentController()
        contentController.add(self, name: "openmatesComposer")
        let configuration = WKWebViewConfiguration()
        configuration.userContentController = contentController
        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.setValue(false, forKey: "drawsBackground")
        webView.setAccessibilityIdentifier("message-editor")
        webView.setAccessibilityLabel("Message editor")
        return webView
    }()
    private let newChatButton = NSButton(title: "New Chat", target: nil, action: nil)
    private let tableView = NSTableView()
    private let tableScrollView = NSScrollView()
    private let statusLabel = NSTextField(labelWithString: "")
    private let progressIndicator = NSProgressIndicator()
    private var tableHeightConstraint: NSLayoutConstraint?
    private var messageText = ""
    private var isMessageEditorReady = false

    override func loadView() {
        view = NSView()
        view.wantsLayer = true
        view.layer?.backgroundColor = NSColor.windowBackgroundColor.cgColor
        preferredContentSize = NSSize(width: 460, height: 480)
        setupUI()
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        extractSharedContent()
        loadRecentChats()
    }

    private func setupUI() {
        let header = NSStackView()
        header.orientation = .horizontal
        header.alignment = .centerY
        header.spacing = Layout.stackSpacing
        header.translatesAutoresizingMaskIntoConstraints = false

        cancelButton.target = self
        cancelButton.action = #selector(cancelTapped)
        cancelButton.bezelStyle = .rounded

        let titleLabel = NSTextField(labelWithString: "OpenMates")
        titleLabel.font = .systemFont(ofSize: 17, weight: .semibold)
        titleLabel.alignment = .center

        sendButton.target = self
        sendButton.action = #selector(sendTapped)
        sendButton.bezelStyle = .rounded
        sendButton.keyEquivalent = "\r"

        header.addArrangedSubview(cancelButton)
        header.addArrangedSubview(titleLabel)
        header.addArrangedSubview(sendButton)
        titleLabel.setContentHuggingPriority(.defaultLow, for: .horizontal)

        rootStack.orientation = .vertical
        rootStack.alignment = .leading
        rootStack.spacing = Layout.stackSpacing
        rootStack.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(rootStack)
        rootStack.addArrangedSubview(header)

        previewLabel.font = .systemFont(ofSize: 13)
        previewLabel.textColor = .secondaryLabelColor
        previewLabel.lineBreakMode = .byTruncatingTail
        previewLabel.maximumNumberOfLines = 4
        previewLabel.wantsLayer = true
        previewLabel.layer?.cornerRadius = 8
        previewLabel.layer?.backgroundColor = NSColor.controlBackgroundColor.cgColor
        rootStack.addArrangedSubview(previewLabel)

        messageComposerView.identifier = NSUserInterfaceItemIdentifier("message-composer")
        messageComposerView.translatesAutoresizingMaskIntoConstraints = false
        messageFieldView.wantsLayer = true
        messageFieldView.layer?.cornerRadius = Layout.composerCornerRadius
        messageFieldView.layer?.borderWidth = Layout.composerBorderWidth
        messageFieldView.layer?.borderColor = NSColor.separatorColor.cgColor
        messageFieldView.layer?.backgroundColor = NSColor.controlBackgroundColor.cgColor
        messageFieldView.identifier = NSUserInterfaceItemIdentifier("message-field")
        messageFieldView.translatesAutoresizingMaskIntoConstraints = false
        messageEditorWebView.translatesAutoresizingMaskIntoConstraints = false
        messageFieldView.addSubview(messageEditorWebView)
        messageComposerView.addSubview(messageFieldView)
        rootStack.addArrangedSubview(messageComposerView)

        newChatButton.target = self
        newChatButton.action = #selector(selectNewChat)
        newChatButton.bezelStyle = .rounded
        rootStack.addArrangedSubview(newChatButton)
        updateNewChatSelection(true)

        let titleColumn = NSTableColumn(identifier: .init("chat"))
        titleColumn.title = "Recent chats"
        tableView.addTableColumn(titleColumn)
        tableView.headerView = nil
        tableView.delegate = self
        tableView.dataSource = self
        tableView.rowHeight = Layout.tableRowHeight
        tableView.intercellSpacing = NSSize(width: 0, height: 4)
        tableView.selectionHighlightStyle = .regular
        tableScrollView.documentView = tableView
        tableScrollView.hasVerticalScroller = false
        tableScrollView.borderType = .noBorder
        rootStack.addArrangedSubview(tableScrollView)
        tableHeightConstraint = tableScrollView.heightAnchor.constraint(equalToConstant: 0)
        tableHeightConstraint?.isActive = true

        statusLabel.font = .systemFont(ofSize: 13)
        statusLabel.textColor = .secondaryLabelColor
        statusLabel.maximumNumberOfLines = 0
        rootStack.addArrangedSubview(statusLabel)

        progressIndicator.style = .spinning
        progressIndicator.controlSize = .small
        progressIndicator.isDisplayedWhenStopped = false
        rootStack.addArrangedSubview(progressIndicator)

        NSLayoutConstraint.activate([
            rootStack.topAnchor.constraint(equalTo: view.topAnchor, constant: Layout.outerPadding),
            rootStack.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: Layout.outerPadding),
            rootStack.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -Layout.outerPadding),
            rootStack.bottomAnchor.constraint(lessThanOrEqualTo: view.bottomAnchor, constant: -Layout.outerPadding),

            header.widthAnchor.constraint(equalTo: rootStack.widthAnchor),
            cancelButton.heightAnchor.constraint(equalToConstant: Layout.buttonHeight),
            sendButton.heightAnchor.constraint(equalToConstant: Layout.buttonHeight),
            previewLabel.widthAnchor.constraint(equalTo: rootStack.widthAnchor),
            messageComposerView.widthAnchor.constraint(equalTo: rootStack.widthAnchor),
            messageComposerView.heightAnchor.constraint(equalToConstant: Layout.messageHeight),
            messageFieldView.topAnchor.constraint(equalTo: messageComposerView.topAnchor),
            messageFieldView.leadingAnchor.constraint(equalTo: messageComposerView.leadingAnchor),
            messageFieldView.trailingAnchor.constraint(equalTo: messageComposerView.trailingAnchor),
            messageFieldView.bottomAnchor.constraint(equalTo: messageComposerView.bottomAnchor),
            messageEditorWebView.topAnchor.constraint(equalTo: messageFieldView.topAnchor),
            messageEditorWebView.leadingAnchor.constraint(equalTo: messageFieldView.leadingAnchor),
            messageEditorWebView.trailingAnchor.constraint(equalTo: messageFieldView.trailingAnchor),
            messageEditorWebView.bottomAnchor.constraint(equalTo: messageFieldView.bottomAnchor),
            newChatButton.widthAnchor.constraint(equalTo: rootStack.widthAnchor),
            tableScrollView.widthAnchor.constraint(equalTo: rootStack.widthAnchor),
            statusLabel.widthAnchor.constraint(equalTo: rootStack.widthAnchor),
        ])
        loadMessageEditorResource()
    }

    private func extractSharedContent() {
        guard let extensionItems = extensionContext?.inputItems as? [NSExtensionItem] else {
            showFailure("Nothing to share.")
            return
        }

        let group = DispatchGroup()
        let collector = SharedPartCollector()

        for item in extensionItems {
            item.attachments?.forEach { provider in
                if provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) {
                    group.enter()
                    provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier) { value, _ in
                        defer { group.leave() }
                        guard let url = Self.sharedFileURL(from: value), Self.isAllowedAttachmentSize(url) else {
                            collector.appendUnsupported(provider.suggestedName ?? "Shared Attachment")
                            return
                        }
                        let accessed = url.startAccessingSecurityScopedResource()
                        defer {
                            if accessed { url.stopAccessingSecurityScopedResource() }
                        }
                        guard let data = try? Data(contentsOf: url) else {
                            collector.appendUnsupported(url.lastPathComponent)
                            return
                        }
                        let filename = url.lastPathComponent
                        let contentType = Self.attachmentContentType(typeIdentifier: UTType.fileURL.identifier, fallbackFilename: filename)
                        guard BackgroundAttachmentClassifier.classification(filename: filename, contentType: contentType) != nil else {
                            collector.appendUnsupported(filename)
                            return
                        }
                        collector.append(SharedAttachment(data: data, filename: filename, contentType: contentType))
                    }
                } else if let attachmentType = Self.firstSupportedAttachmentType(from: provider) {
                    group.enter()
                    let filename = Self.attachmentFilename(from: provider, typeIdentifier: attachmentType)
                    let contentType = Self.attachmentContentType(typeIdentifier: attachmentType, fallbackFilename: filename)
                    provider.loadDataRepresentation(forTypeIdentifier: attachmentType) { data, _ in
                        defer { group.leave() }
                        guard let data, data.count <= BackgroundAttachmentClassifier.maxFileSizeBytes else {
                            collector.appendUnsupported(filename)
                            return
                        }
                        collector.append(SharedAttachment(data: data, filename: filename, contentType: contentType))
                    }
                } else if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
                    group.enter()
                    provider.loadItem(forTypeIdentifier: UTType.url.identifier) { value, _ in
                        defer { group.leave() }
                        if let text = Self.sharedURLText(from: value) {
                            collector.append(SharedPart(text: text, isURL: true))
                        }
                    }
                } else if provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
                    group.enter()
                    provider.loadItem(forTypeIdentifier: UTType.plainText.identifier) { value, _ in
                        defer { group.leave() }
                        if let text = Self.sharedPlainText(from: value) {
                            collector.append(SharedPart(text: text, isURL: false))
                        }
                    }
                } else if let name = provider.suggestedName {
                    collector.appendUnsupported(name)
                }
            }
        }

        group.notify(queue: .main) { [weak self] in
            guard let self else { return }
            sharedParts = collector.values().filter { !$0.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
            sharedAttachments = collector.attachmentValues()
            unsupportedAttachments = collector.unsupportedValues()
            updatePreview()
        }
    }

    private func updatePreview() {
        let sharedText = sharedParts.map(\.text).joined(separator: "\n")
        var previewLines: [String] = []
        if !sharedText.isEmpty { previewLines.append(sharedText) }
        if !sharedAttachments.isEmpty {
            previewLines.append("Attachments: \(sharedAttachments.map(\.filename).joined(separator: ", "))")
        }
        if !unsupportedAttachments.isEmpty {
            previewLines.append("Unsupported: \(unsupportedAttachments.joined(separator: ", "))")
        }
        previewLabel.stringValue = previewLines.isEmpty ? "No supported URL, text, or file was found." : previewLines.joined(separator: "\n")
        messageText = ""
        syncMessageEditorText()
        sendButton.isEnabled = !sharedText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !sharedAttachments.isEmpty
    }

    private func loadRecentChats() {
        progressIndicator.startAnimation(nil)
        statusLabel.stringValue = "Loading recent chats..."
        Task {
            do {
                let chats = try await sender.loadRecentChats()
                recentChats = chats
                tableView.reloadData()
                updateTableHeight()
                statusLabel.textColor = .secondaryLabelColor
                statusLabel.stringValue = chats.isEmpty ? "New Chat is ready." : "Choose a recent chat or keep New Chat selected."
                progressIndicator.stopAnimation(nil)
            } catch {
                progressIndicator.stopAnimation(nil)
                statusLabel.textColor = .secondaryLabelColor
                statusLabel.stringValue = error.localizedDescription
            }
        }
    }

    @objc private func cancelTapped() {
        extensionContext?.completeRequest(returningItems: nil)
    }

    @objc private func selectNewChat() {
        selectedChat = nil
        tableView.deselectAll(nil)
        updateNewChatSelection(true)
    }

    @objc private func sendTapped() {
        guard !isSubmitting else { return }
        isSubmitting = true
        sendButton.isEnabled = false
        cancelButton.isEnabled = false
        progressIndicator.startAnimation(nil)
        statusLabel.textColor = .secondaryLabelColor
        statusLabel.stringValue = "Sending..."

        Task {
            do {
                let finalMessage = try buildFinalMessage()
                let destination = selectedChat ?? draftDestinationForAttachments()
                let embeds = try await prepareSharedAttachments(destination: destination)
                _ = try await sender.send(.init(content: finalMessage, destination: destination, embeds: embeds))
                extensionContext?.completeRequest(returningItems: nil)
            } catch {
                showFailure(error.localizedDescription)
                isSubmitting = false
                sendButton.isEnabled = true
                cancelButton.isEnabled = true
                progressIndicator.stopAnimation(nil)
            }
        }
    }

    private func buildFinalMessage() throws -> String {
        let userText = messageText.trimmingCharacters(in: .whitespacesAndNewlines)
        let sharedText = sharedParts.map(\.text).joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
        let message: String
        if userText.isEmpty {
            message = sharedText
        } else if sharedText.isEmpty {
            message = userText
        } else {
            message = "\(userText)\n\n\(sharedText)"
        }
        guard !message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !sharedAttachments.isEmpty else {
            throw BackgroundChatSendError.emptyMessage
        }
        return message
    }

    private func draftDestinationForAttachments() -> BackgroundChatSender.DestinationChat? {
        guard !sharedAttachments.isEmpty, selectedChat == nil else { return selectedChat }
        return BackgroundChatSender.DestinationChat(
            id: UUID().uuidString.lowercased(),
            title: "New Chat",
            lastMessageAt: nil,
            createdAt: ISO8601DateFormatter().string(from: Date()),
            updatedAt: nil,
            appId: nil,
            encryptedTitle: nil,
            encryptedCategory: nil,
            encryptedIcon: nil,
            encryptedChatKey: nil,
            messagesV: 0,
            titleV: 0
        )
    }

    private func prepareSharedAttachments(destination: BackgroundChatSender.DestinationChat?) async throws -> [BackgroundPreparedEmbed] {
        guard !sharedAttachments.isEmpty else { return [] }
        let chatId = destination?.id ?? UUID().uuidString.lowercased()
        var embeds: [BackgroundPreparedEmbed] = []
        for attachment in sharedAttachments {
            let embed = try await sender.prepareAttachment(
                data: attachment.data,
                filename: attachment.filename,
                contentType: attachment.contentType,
                chatId: chatId
            )
            embeds.append(embed)
        }
        return embeds
    }

    private func updateNewChatSelection(_ selected: Bool) {
        newChatButton.contentTintColor = selected ? .controlAccentColor : .labelColor
    }

    private func updateTableHeight() {
        let visibleRows = min(recentChats.count, Layout.tableMaxVisibleRows)
        tableHeightConstraint?.constant = CGFloat(visibleRows) * (Layout.tableRowHeight + tableView.intercellSpacing.height)
        tableScrollView.hasVerticalScroller = recentChats.count > Layout.tableMaxVisibleRows
    }

    private func showFailure(_ message: String) {
        statusLabel.textColor = .systemRed
        statusLabel.stringValue = message
    }

    private func updateSendButtonState() {
        let sharedText = sharedParts.map(\.text).joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
        let hasUserText = !messageText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        sendButton.isEnabled = !isSubmitting && (hasUserText || !sharedText.isEmpty || !sharedAttachments.isEmpty)
    }

    private func syncMessageEditorText() {
        guard isMessageEditorReady else { return }
        messageEditorWebView.setAccessibilityValue(messageText)
        sendMessageEditorCommand(["type": "setPlaceholder", "placeholder": "Add a message"])
        sendMessageEditorCommand(["type": "setContent", "text": messageText])
    }

    private func loadMessageEditorResource() {
        guard let url = Bundle.main.url(forResource: "index", withExtension: "html", subdirectory: "TiptapComposer") else {
            showFailure("Message editor failed to load.")
            return
        }
        messageEditorWebView.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent())
    }

    private func sendMessageEditorCommand(_ command: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: command),
              let json = String(data: data, encoding: .utf8) else {
            return
        }
        messageEditorWebView.evaluateJavaScript("window.OpenMatesComposer && window.OpenMatesComposer.receive(\(json));")
    }
}

extension MacShareViewController: WKScriptMessageHandler, WKNavigationDelegate {
    nonisolated func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        MainActor.assumeIsolated {
            guard let body = message.body as? [String: Any], let type = body["type"] as? String else { return }
            switch type {
            case "ready":
                isMessageEditorReady = true
                syncMessageEditorText()
            case "contentChanged":
                messageText = body["text"] as? String ?? ""
                messageEditorWebView.setAccessibilityValue(messageText)
                updateSendButtonState()
            case "submit":
                sendTapped()
            default:
                break
            }
        }
    }

    nonisolated func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
    ) {
        guard let url = navigationAction.request.url else {
            decisionHandler(.cancel)
            return
        }
        decisionHandler((url.isFileURL || url.scheme == "about") ? .allow : .cancel)
    }
}

extension MacShareViewController: NSTableViewDataSource, NSTableViewDelegate {
    nonisolated func numberOfRows(in tableView: NSTableView) -> Int {
        MainActor.assumeIsolated {
            recentChats.count
        }
    }

    nonisolated func tableView(_ tableView: NSTableView, viewFor tableColumn: NSTableColumn?, row: Int) -> NSView? {
        MainActor.assumeIsolated {
            let identifier = NSUserInterfaceItemIdentifier("ChatDestinationCell")
            let existingCell = tableView.makeView(withIdentifier: identifier, owner: self) as? NSTableCellView
            let cell = existingCell ?? NSTableCellView()
            cell.identifier = identifier

            let textField: NSTextField
            if let existingTextField = cell.textField {
                textField = existingTextField
            } else {
                textField = NSTextField(labelWithString: "")
                textField.translatesAutoresizingMaskIntoConstraints = false
                cell.addSubview(textField)
                cell.textField = textField
                NSLayoutConstraint.activate([
                    textField.leadingAnchor.constraint(equalTo: cell.leadingAnchor, constant: 10),
                    textField.trailingAnchor.constraint(equalTo: cell.trailingAnchor, constant: -10),
                    textField.centerYAnchor.constraint(equalTo: cell.centerYAnchor),
                ])
            }

            textField.font = .systemFont(ofSize: 14, weight: .medium)
            textField.lineBreakMode = .byTruncatingTail
            textField.stringValue = recentChats[row].displayTitle
            return cell
        }
    }

    nonisolated func tableViewSelectionDidChange(_ notification: Notification) {
        MainActor.assumeIsolated {
            let row = tableView.selectedRow
            guard row >= 0, row < recentChats.count else { return }
            selectedChat = recentChats[row]
            updateNewChatSelection(false)
        }
    }
}
