// Share extension for sending URLs and text into encrypted OpenMates chats.
// The extension stays focused: preview shared content, let the user add a task
// instruction, choose a new or recent chat, then send through the shared native
// background chat pipeline. Files, audio, camera, sketch, and location are out
// of scope for this v1 flow.

import UIKit
import UniformTypeIdentifiers

final class ShareViewController: UIViewController {
    private var sharedParts: [SharedPart] = []
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
        header.addArrangedSubview(headerLabel)

        sendButton.setTitle("Send", for: .normal)
        sendButton.titleLabel?.font = .systemFont(ofSize: 17, weight: .semibold)
        sendButton.addTarget(self, action: #selector(sendTapped), for: .touchUpInside)
        header.addArrangedSubview(sendButton)

        scrollView.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(scrollView)

        stackView.axis = .vertical
        stackView.spacing = 14
        stackView.translatesAutoresizingMaskIntoConstraints = false
        scrollView.addSubview(stackView)

        previewLabel.font = .systemFont(ofSize: 13, weight: .regular)
        previewLabel.textColor = .secondaryLabel
        previewLabel.numberOfLines = 4
        previewLabel.layer.cornerRadius = 10
        previewLabel.layer.masksToBounds = true
        previewLabel.backgroundColor = .secondarySystemBackground
        stackView.addArrangedSubview(previewLabel)

        messageTextView.font = .systemFont(ofSize: 16)
        messageTextView.layer.borderColor = UIColor.separator.cgColor
        messageTextView.layer.borderWidth = 1
        messageTextView.layer.cornerRadius = 12
        messageTextView.textContainerInset = UIEdgeInsets(top: 12, left: 10, bottom: 12, right: 10)
        messageTextView.heightAnchor.constraint(equalToConstant: 116).isActive = true
        stackView.addArrangedSubview(messageTextView)

        newChatButton.setTitle("New Chat", for: .normal)
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
        chatTableView.rowHeight = 50
        chatTableView.separatorStyle = .none
        chatTableView.backgroundColor = .clear
        stackView.addArrangedSubview(chatTableView)
        tableHeightConstraint = chatTableView.heightAnchor.constraint(equalToConstant: 0)
        tableHeightConstraint?.isActive = true

        statusLabel.font = .systemFont(ofSize: 13)
        statusLabel.textColor = .secondaryLabel
        statusLabel.numberOfLines = 0
        stackView.addArrangedSubview(statusLabel)

        spinner.hidesWhenStopped = true
        stackView.addArrangedSubview(spinner)

        NSLayoutConstraint.activate([
            header.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 10),
            header.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 16),
            header.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -16),

            scrollView.topAnchor.constraint(equalTo: header.bottomAnchor, constant: 14),
            scrollView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            scrollView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            scrollView.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor),

            stackView.topAnchor.constraint(equalTo: scrollView.topAnchor),
            stackView.leadingAnchor.constraint(equalTo: scrollView.leadingAnchor, constant: 16),
            stackView.trailingAnchor.constraint(equalTo: scrollView.trailingAnchor, constant: -16),
            stackView.bottomAnchor.constraint(equalTo: scrollView.bottomAnchor, constant: -20),
            stackView.widthAnchor.constraint(equalTo: scrollView.widthAnchor, constant: -32),
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
        previewLabel.text = sharedText.isEmpty ? "No URL or text was found." : sharedText
        messageTextView.text = ""
        sendButton.isEnabled = !sharedText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
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
                    tableHeightConstraint?.constant = CGFloat(chats.count) * 50
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
                _ = try await sender.send(.init(content: finalMessage, destination: selectedChat))
                await MainActor.run {
                    extensionContext?.completeRequest(returningItems: nil)
                }
            } catch {
                await MainActor.run {
                    showFailure(error.localizedDescription)
                    isSubmitting = false
                    sendButton.isEnabled = true
                    cancelButton.isEnabled = true
                    spinner.stopAnimating()
                }
            }
        }
    }

    private func buildFinalMessage() throws -> String {
        let userText = messageTextView.text.trimmingCharacters(in: .whitespacesAndNewlines)
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
        newChatButton.backgroundColor = selected ? .systemBlue.withAlphaComponent(0.12) : .secondarySystemBackground
        newChatButton.layer.borderColor = selected ? UIColor.systemBlue.cgColor : UIColor.clear.cgColor
        newChatButton.layer.borderWidth = selected ? 1 : 0
    }

    private func showFailure(_ message: String) {
        statusLabel.textColor = .systemRed
        statusLabel.text = message
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
        cell.configure(title: recentChats[indexPath.row].displayTitle)
        return cell
    }

    func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        selectedChat = recentChats[indexPath.row]
        selectedIndexPath = indexPath
        updateNewChatSelection(false)
    }
}

private final class ChatDestinationCell: UITableViewCell {
    static let reuseIdentifier = "ChatDestinationCell"

    private let titleLabel = UILabel()

    override init(style: UITableViewCell.CellStyle, reuseIdentifier: String?) {
        super.init(style: style, reuseIdentifier: reuseIdentifier)
        selectionStyle = .none
        backgroundColor = .clear

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

    func configure(title: String) {
        titleLabel.text = title
    }
}
