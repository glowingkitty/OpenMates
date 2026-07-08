// Share extension for sending URLs, text, and supported files into encrypted
// OpenMates chats. The extension stays focused: preview shared content, let the
// user add a task instruction, choose New Chat or a recent chat, then send
// through the shared native background chat pipeline with embed parity.

// ─── Web source ─────────────────────────────────────────────────────
// Svelte:  frontend/packages/ui/src/components/enter_message/MessageInput.svelte
// CSS:     frontend/packages/ui/src/components/enter_message/MessageInput.styles.css
//          Classes: .message-field, .action-buttons
// Tokens:  ColorTokens.generated.swift, SpacingTokens.generated.swift,
//          TypographyTokens.generated.swift
// ────────────────────────────────────────────────────────────────────

import UIKit
import UniformTypeIdentifiers

final class ShareViewController: UIViewController {
    fileprivate enum Layout {
        static let chatRowHeight: CGFloat = 50
        static let maxVisibleChatRows = 5
        static let selectedBorderWidth: CGFloat = 1
        static let selectedBackgroundAlpha: CGFloat = 0.12
        static let cellCornerRadius: CGFloat = 10
        static let composerCornerRadius: CGFloat = 24
        static let composerBorderWidth: CGFloat = 2
        static let composerHeight: CGFloat = 116
        static let composerHorizontalInset: CGFloat = 16
        static let composerTopInset: CGFloat = 16
        static let composerBottomInset: CGFloat = 60
        static let composerSendHeight: CGFloat = 40
        static let composerSendTrailing: CGFloat = 12
        static let composerSendBottom: CGFloat = 12
    }

    private var sharedParts: [SharedPart] = []
    private var sharedAttachments: [SharedAttachment] = []
    private var unsupportedAttachments: [String] = []
    private var recentChats: [BackgroundChatSender.DestinationChat] = []
    private var selectedChat: BackgroundChatSender.DestinationChat?
    private var selectedIndexPath: IndexPath?
    private var isSubmitting = false

    private let sender = BackgroundChatSender()
    private let scrollView = UIScrollView()
    private let stackView = UIStackView()
    private let headerLabel = UILabel()
    private let cancelButton = UIButton(type: .system)
    private let sendButton = UIButton(type: .system)
    private let previewLabel = UILabel()
    private let messageComposerView = UIView()
    private let messageFieldView = UIView()
    private let messageTextView = UITextView()
    private let newChatButton = UIButton(type: .system)
    private let chatTableView = UITableView(frame: .zero, style: .plain)
    private let statusLabel = UILabel()
    private let spinner = UIActivityIndicatorView(style: .medium)
    private var tableHeightConstraint: NSLayoutConstraint?

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

    nonisolated private static func sharedURLText(from value: Any?) -> String? {
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

    nonisolated private static func sharedFileURL(from value: Any?) -> URL? {
        if let url = value as? URL { return url.isFileURL ? url : nil }
        if let url = value as? NSURL, url.isFileURL { return url as URL }
        return nil
    }

    nonisolated private static func sharedPlainText(from value: Any?) -> String? {
        if let text = value as? String {
            return text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : text
        }
        if let text = value as? NSString {
            let string = text as String
            return string.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : string
        }
        return nil
    }

    nonisolated private static func attachmentFilename(from provider: NSItemProvider, typeIdentifier: String) -> String {
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

    nonisolated private static func attachmentContentType(typeIdentifier: String, fallbackFilename: String) -> String {
        if let mime = UTType(typeIdentifier)?.preferredMIMEType { return mime }
        if let type = UTType(filenameExtension: URL(fileURLWithPath: fallbackFilename).pathExtension), let mime = type.preferredMIMEType {
            return mime
        }
        return "application/octet-stream"
    }

    nonisolated private static func firstSupportedAttachmentType(from provider: NSItemProvider) -> String? {
        provider.registeredTypeIdentifiers.first { identifier in
            let filename = attachmentFilename(from: provider, typeIdentifier: identifier)
            let contentType = attachmentContentType(typeIdentifier: identifier, fallbackFilename: filename)
            return BackgroundAttachmentClassifier.classification(filename: filename, contentType: contentType) != nil
        }
    }

    nonisolated private static func isAllowedAttachmentSize(_ url: URL) -> Bool {
        guard let values = try? url.resourceValues(forKeys: [.fileSizeKey]), let size = values.fileSize else {
            return false
        }
        return size <= BackgroundAttachmentClassifier.maxFileSizeBytes
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        setupUI()
        extractSharedContent()
        loadRecentChats()
    }

    private func setupUI() {
        view.backgroundColor = .systemBackground

        let header = UIStackView()
        header.axis = .horizontal
        header.alignment = .center
        header.spacing = 12
        header.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(header)

        cancelButton.setTitle("Cancel", for: .normal)
        cancelButton.addTarget(self, action: #selector(cancelTapped), for: .touchUpInside)
        header.addArrangedSubview(cancelButton)

        headerLabel.text = "OpenMates"
        headerLabel.font = .systemFont(ofSize: 17, weight: .semibold)
        headerLabel.textAlignment = .center
        headerLabel.setContentHuggingPriority(.defaultLow, for: .horizontal)
        header.addArrangedSubview(headerLabel)

        sendButton.setTitle("Send", for: .normal)
        sendButton.titleLabel?.font = .systemFont(ofSize: 17, weight: .semibold)
        sendButton.addTarget(self, action: #selector(sendTapped), for: .touchUpInside)
        let trailingSpacer = UIView()
        header.addArrangedSubview(trailingSpacer)

        scrollView.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(scrollView)

        stackView.axis = .vertical
        stackView.spacing = 14
        stackView.translatesAutoresizingMaskIntoConstraints = false
        scrollView.addSubview(stackView)

        previewLabel.font = .systemFont(ofSize: 13, weight: .regular)
        previewLabel.textColor = .secondaryLabel
        previewLabel.numberOfLines = 4
        previewLabel.accessibilityIdentifier = "share-extension-preview"
        previewLabel.layer.cornerRadius = 10
        previewLabel.layer.masksToBounds = true
        previewLabel.backgroundColor = .secondarySystemBackground
        stackView.addArrangedSubview(previewLabel)

        messageComposerView.accessibilityIdentifier = "message-composer"
        messageFieldView.accessibilityIdentifier = "message-field"
        messageFieldView.backgroundColor = .omGreyBlue
        messageFieldView.layer.borderColor = UIColor.clear.cgColor
        messageFieldView.layer.borderWidth = 0
        messageFieldView.layer.cornerRadius = Layout.composerCornerRadius
        messageFieldView.layer.masksToBounds = false
        messageFieldView.layer.shadowColor = UIColor.black.cgColor
        messageFieldView.layer.shadowOpacity = 0.08
        messageFieldView.layer.shadowRadius = 12
        messageFieldView.layer.shadowOffset = CGSize(width: 0, height: 4)
        messageTextView.font = UIFont(name: "LexendDeca-Regular", size: 16) ?? .systemFont(ofSize: 16)
        messageTextView.accessibilityIdentifier = "share-extension-message-input"
        messageTextView.backgroundColor = .clear
        messageTextView.textColor = .omFontPrimary
        messageTextView.tintColor = .omButtonPrimary
        messageTextView.delegate = self
        messageTextView.textContainerInset = UIEdgeInsets(
            top: Layout.composerTopInset,
            left: Layout.composerHorizontalInset - 5,
            bottom: Layout.composerBottomInset,
            right: 90
        )
        messageTextView.translatesAutoresizingMaskIntoConstraints = false
        messageFieldView.translatesAutoresizingMaskIntoConstraints = false
        sendButton.backgroundColor = .omButtonPrimary
        sendButton.tintColor = .white
        sendButton.layer.cornerRadius = 20
        sendButton.contentEdgeInsets = UIEdgeInsets(top: 6, left: 16, bottom: 6, right: 16)
        sendButton.translatesAutoresizingMaskIntoConstraints = false
        messageFieldView.addSubview(messageTextView)
        messageFieldView.addSubview(sendButton)
        messageComposerView.addSubview(messageFieldView)
        stackView.addArrangedSubview(messageComposerView)

        newChatButton.setTitle("New Chat", for: .normal)
        newChatButton.accessibilityIdentifier = "share-extension-new-chat"
        newChatButton.titleLabel?.font = .systemFont(ofSize: 15, weight: .semibold)
        newChatButton.contentHorizontalAlignment = .leading
        var newChatConfiguration = UIButton.Configuration.plain()
        newChatConfiguration.contentInsets = NSDirectionalEdgeInsets(top: 12, leading: 14, bottom: 12, trailing: 14)
        newChatButton.configuration = newChatConfiguration
        newChatButton.layer.cornerRadius = 10
        newChatButton.addTarget(self, action: #selector(selectNewChat), for: .touchUpInside)
        stackView.addArrangedSubview(newChatButton)
        updateNewChatSelection(true)

        chatTableView.dataSource = self
        chatTableView.delegate = self
        chatTableView.register(ChatDestinationCell.self, forCellReuseIdentifier: ChatDestinationCell.reuseIdentifier)
        chatTableView.isScrollEnabled = false
        chatTableView.rowHeight = Layout.chatRowHeight
        chatTableView.separatorStyle = .none
        chatTableView.backgroundColor = .clear
        stackView.addArrangedSubview(chatTableView)
        tableHeightConstraint = chatTableView.heightAnchor.constraint(equalToConstant: 0)
        tableHeightConstraint?.isActive = true

        statusLabel.font = .systemFont(ofSize: 13)
        statusLabel.accessibilityIdentifier = "share-extension-status"
        statusLabel.textColor = .secondaryLabel
        statusLabel.numberOfLines = 0
        stackView.addArrangedSubview(statusLabel)

        spinner.hidesWhenStopped = true
        stackView.addArrangedSubview(spinner)

        NSLayoutConstraint.activate([
            header.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 10),
            header.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 16),
            header.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -16),
            trailingSpacer.widthAnchor.constraint(equalTo: cancelButton.widthAnchor),

            scrollView.topAnchor.constraint(equalTo: header.bottomAnchor, constant: 14),
            scrollView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            scrollView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            scrollView.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor),

            stackView.topAnchor.constraint(equalTo: scrollView.topAnchor),
            stackView.leadingAnchor.constraint(equalTo: scrollView.leadingAnchor, constant: 16),
            stackView.trailingAnchor.constraint(equalTo: scrollView.trailingAnchor, constant: -16),
            stackView.bottomAnchor.constraint(equalTo: scrollView.bottomAnchor, constant: -20),
            stackView.widthAnchor.constraint(equalTo: scrollView.widthAnchor, constant: -32),

            messageFieldView.topAnchor.constraint(equalTo: messageComposerView.topAnchor),
            messageFieldView.leadingAnchor.constraint(equalTo: messageComposerView.leadingAnchor),
            messageFieldView.trailingAnchor.constraint(equalTo: messageComposerView.trailingAnchor),
            messageFieldView.bottomAnchor.constraint(equalTo: messageComposerView.bottomAnchor),
            messageFieldView.heightAnchor.constraint(equalToConstant: Layout.composerHeight),
            messageTextView.topAnchor.constraint(equalTo: messageFieldView.topAnchor),
            messageTextView.leadingAnchor.constraint(equalTo: messageFieldView.leadingAnchor),
            messageTextView.trailingAnchor.constraint(equalTo: messageFieldView.trailingAnchor),
            messageTextView.bottomAnchor.constraint(equalTo: messageFieldView.bottomAnchor),
            sendButton.trailingAnchor.constraint(equalTo: messageFieldView.trailingAnchor, constant: -Layout.composerSendTrailing),
            sendButton.bottomAnchor.constraint(equalTo: messageFieldView.bottomAnchor, constant: -Layout.composerSendBottom),
            sendButton.heightAnchor.constraint(equalToConstant: Layout.composerSendHeight),
        ])

        sendButton.accessibilityIdentifier = "share-extension-send"
        cancelButton.accessibilityIdentifier = "share-extension-cancel"
        view.accessibilityIdentifier = "share-extension-root"
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
                        guard let url = Self.sharedFileURL(from: value), Self.isAllowedAttachmentSize(url), let data = try? Data(contentsOf: url) else {
                            collector.appendUnsupported(provider.suggestedName ?? "Shared Attachment")
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
        previewLabel.text = previewLines.isEmpty ? "No supported URL, text, or file was found." : previewLines.joined(separator: "\n")
        messageTextView.text = sharedText
        updateSendButtonState()
    }

    private func loadRecentChats() {
        spinner.startAnimating()
        statusLabel.text = "Loading recent chats..."
        Task {
            do {
                let chats = try await sender.loadRecentChats()
                await MainActor.run {
                    spinner.stopAnimating()
                    statusLabel.text = chats.isEmpty ? "New Chat is ready." : "Choose a recent chat or keep New Chat selected."
                    recentChats = chats
                    let visibleRows = min(chats.count, Layout.maxVisibleChatRows)
                    tableHeightConstraint?.constant = CGFloat(visibleRows) * Layout.chatRowHeight
                    chatTableView.isScrollEnabled = chats.count > Layout.maxVisibleChatRows
                    chatTableView.reloadData()
                }
            } catch {
                await MainActor.run {
                    spinner.stopAnimating()
                    statusLabel.text = error.localizedDescription
                }
            }
        }
    }

    @objc private func cancelTapped() {
        extensionContext?.completeRequest(returningItems: nil)
    }

    @objc private func selectNewChat() {
        selectedChat = nil
        if let selectedIndexPath {
            chatTableView.deselectRow(at: selectedIndexPath, animated: true)
        }
        selectedIndexPath = nil
        updateNewChatSelection(true)
        chatTableView.reloadData()
    }

    @objc private func sendTapped() {
        guard !isSubmitting else { return }
        isSubmitting = true
        sendButton.isEnabled = false
        cancelButton.isEnabled = false
        spinner.startAnimating()
        statusLabel.textColor = .secondaryLabel
        statusLabel.text = "Sending..."

        Task {
            do {
                let finalMessage = try buildFinalMessage()
                let destination = selectedChat ?? draftDestinationForAttachments()
                let embeds = try await prepareSharedAttachments(destination: destination)
                _ = try await sender.send(.init(content: finalMessage, destination: destination, embeds: embeds))
                await MainActor.run {
                    extensionContext?.completeRequest(returningItems: nil)
                }
            } catch {
                await MainActor.run {
                    showFailure(error.localizedDescription)
                    isSubmitting = false
                    updateSendButtonState()
                    cancelButton.isEnabled = true
                    spinner.stopAnimating()
                }
            }
        }
    }

    private func buildFinalMessage() throws -> String {
        let userText = messageTextView.text.trimmingCharacters(in: .whitespacesAndNewlines)
        let sharedText = sharedParts.map(\.text).joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
        let message = userText.isEmpty ? sharedText : userText
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
        newChatButton.backgroundColor = selected ? .systemBlue.withAlphaComponent(0.12) : .secondarySystemBackground
        newChatButton.layer.borderColor = selected ? UIColor.systemBlue.cgColor : UIColor.clear.cgColor
        newChatButton.layer.borderWidth = selected ? 1 : 0
    }

    private func updateSendButtonState() {
        let hasText = !messageTextView.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        sendButton.isEnabled = !isSubmitting && (hasText || !sharedAttachments.isEmpty)
        sendButton.alpha = sendButton.isEnabled ? 1 : 0.6
    }

    private func showFailure(_ message: String) {
        statusLabel.textColor = .systemRed
        statusLabel.text = message
    }
}

extension ShareViewController: UITextViewDelegate {
    func textViewDidChange(_ textView: UITextView) {
        updateSendButtonState()
    }
}

extension ShareViewController: UITableViewDataSource, UITableViewDelegate {
    func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int {
        recentChats.count
    }

    func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let cell = tableView.dequeueReusableCell(
            withIdentifier: ChatDestinationCell.reuseIdentifier,
            for: indexPath
        ) as! ChatDestinationCell
        let chat = recentChats[indexPath.row]
        cell.configure(title: chat.displayTitle, isSelected: selectedChat?.id == chat.id)
        return cell
    }

    func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        selectedChat = recentChats[indexPath.row]
        selectedIndexPath = indexPath
        updateNewChatSelection(false)
        tableView.reloadData()
    }
}

private extension UIColor {
    static let omGreyBlue = UIColor(named: "grey-blue") ?? UIColor(red: 0.09, green: 0.15, blue: 0.20, alpha: 1)
    static let omFontPrimary = UIColor(named: "font-primary") ?? .label
    static let omButtonPrimary = UIColor(red: 1.0, green: 0.333, blue: 0.231, alpha: 1)
}

private final class ChatDestinationCell: UITableViewCell {
    static let reuseIdentifier = "ChatDestinationCell"

    private let titleLabel = UILabel()

    override init(style: UITableViewCell.CellStyle, reuseIdentifier: String?) {
        super.init(style: style, reuseIdentifier: reuseIdentifier)
        selectionStyle = .none
        backgroundColor = .clear
        contentView.layer.cornerRadius = ShareViewController.Layout.cellCornerRadius
        contentView.layer.masksToBounds = true

        titleLabel.font = .systemFont(ofSize: 15, weight: .medium)
        titleLabel.translatesAutoresizingMaskIntoConstraints = false
        contentView.addSubview(titleLabel)

        NSLayoutConstraint.activate([
            titleLabel.leadingAnchor.constraint(equalTo: contentView.leadingAnchor, constant: 14),
            titleLabel.trailingAnchor.constraint(equalTo: contentView.trailingAnchor, constant: -14),
            titleLabel.centerYAnchor.constraint(equalTo: contentView.centerYAnchor),
        ])
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    func configure(title: String, isSelected: Bool) {
        titleLabel.text = title
        accessibilityIdentifier = "share-extension-chat-destination"
        accessibilityLabel = title
        accessibilityValue = isSelected ? "Selected" : "Not selected"
        isAccessibilityElement = true
        contentView.backgroundColor = isSelected ? .systemBlue.withAlphaComponent(ShareViewController.Layout.selectedBackgroundAlpha) : .secondarySystemBackground
        contentView.layer.borderColor = isSelected ? UIColor.systemBlue.cgColor : UIColor.clear.cgColor
        contentView.layer.borderWidth = isSelected ? ShareViewController.Layout.selectedBorderWidth : 0
    }
}
