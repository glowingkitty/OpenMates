// macOS share extension for sending URLs and text into encrypted chats.
// This mirrors the focused iOS share flow with an AppKit host controller:
// preview shared content, add an optional instruction, choose New Chat or a
// recent chat, then send through BackgroundChatSender. Rich attachments,
// audio, camera, sketch, and location are intentionally out of scope for v1.
// Secrets remain in the shared Keychain access group; App Group defaults are
// used only for cached session metadata needed by extension processes.

import AppKit
import UniformTypeIdentifiers

@MainActor
final class MacShareViewController: NSViewController {
    private enum Layout {
        static let outerPadding: CGFloat = 18
        static let stackSpacing: CGFloat = 12
        static let buttonHeight: CGFloat = 34
        static let messageHeight: CGFloat = 112
        static let tableRowHeight: CGFloat = 42
        static let tableMaxVisibleRows = 5
    }

    private struct SharedPart {
        let text: String
        let isURL: Bool
    }

    private final class SharedPartCollector: @unchecked Sendable {
        private var parts: [SharedPart] = []
        private let lock = NSLock()

        func append(_ part: SharedPart) {
            lock.lock()
            parts.append(part)
            lock.unlock()
        }

        func values() -> [SharedPart] {
            lock.lock()
            let snapshot = parts
            lock.unlock()
            return snapshot
        }
    }

    private var sharedParts: [SharedPart] = []
    private var recentChats: [BackgroundChatSender.DestinationChat] = []
    private var selectedChat: BackgroundChatSender.DestinationChat?
    private var isSubmitting = false

    private let sender = BackgroundChatSender()
    private let rootStack = NSStackView()
    private let cancelButton = NSButton(title: "Cancel", target: nil, action: nil)
    private let sendButton = NSButton(title: "Send", target: nil, action: nil)
    private let previewLabel = NSTextField(labelWithString: "")
    private let messageTextView = NSTextView()
    private let newChatButton = NSButton(title: "New Chat", target: nil, action: nil)
    private let tableView = NSTableView()
    private let tableScrollView = NSScrollView()
    private let statusLabel = NSTextField(labelWithString: "")
    private let progressIndicator = NSProgressIndicator()
    private var tableHeightConstraint: NSLayoutConstraint?

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

        let messageScrollView = NSScrollView()
        messageScrollView.hasVerticalScroller = true
        messageScrollView.borderType = .bezelBorder
        messageScrollView.documentView = messageTextView
        messageTextView.font = .systemFont(ofSize: 15)
        messageTextView.isRichText = false
        messageTextView.allowsUndo = true
        rootStack.addArrangedSubview(messageScrollView)

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
            messageScrollView.widthAnchor.constraint(equalTo: rootStack.widthAnchor),
            messageScrollView.heightAnchor.constraint(equalToConstant: Layout.messageHeight),
            newChatButton.widthAnchor.constraint(equalTo: rootStack.widthAnchor),
            tableScrollView.widthAnchor.constraint(equalTo: rootStack.widthAnchor),
            statusLabel.widthAnchor.constraint(equalTo: rootStack.widthAnchor),
        ])
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
                if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
                    group.enter()
                    provider.loadItem(forTypeIdentifier: UTType.url.identifier) { value, _ in
                        if let url = value as? URL {
                            collector.append(SharedPart(text: url.absoluteString, isURL: true))
                        } else if let url = value as? NSURL {
                            collector.append(SharedPart(text: url.absoluteString ?? "", isURL: true))
                        }
                        group.leave()
                    }
                } else if provider.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
                    group.enter()
                    provider.loadItem(forTypeIdentifier: UTType.plainText.identifier) { value, _ in
                        if let text = value as? String {
                            collector.append(SharedPart(text: text, isURL: false))
                        }
                        group.leave()
                    }
                }
            }
        }

        group.notify(queue: .main) { [weak self] in
            guard let self else { return }
            sharedParts = collector.values().filter { !$0.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
            updatePreview()
        }
    }

    private func updatePreview() {
        let sharedText = sharedParts.map(\.text).joined(separator: "\n")
        previewLabel.stringValue = sharedText.isEmpty ? "No URL or text was found." : sharedText
        messageTextView.string = ""
        sendButton.isEnabled = !sharedText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
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
                _ = try await sender.send(.init(content: finalMessage, destination: selectedChat))
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
        let userText = messageTextView.string.trimmingCharacters(in: .whitespacesAndNewlines)
        let sharedText = sharedParts.map(\.text).joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
        let message: String
        if userText.isEmpty {
            message = sharedText
        } else if sharedText.isEmpty {
            message = userText
        } else {
            message = "\(userText)\n\n\(sharedText)"
        }
        guard !message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw BackgroundChatSendError.emptyMessage
        }
        return message
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
