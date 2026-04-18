// Share extension — receives shared content (URLs, text, images) from other apps
// and sends it to a new or existing OpenMates chat. Loads recent chats from the
// API so the user can pick a destination. Uses the shared App Group cookie storage
// for authentication without a separate login.

import UIKit
import UniformTypeIdentifiers

class ShareViewController: UIViewController {
    private var sharedItems: [SharedItem] = []
    private var recentChats: [RecentChat] = []
    private var selectedChat: RecentChat?
    private var isSubmitting = false
    private var isLoadingChats = true

    // UI elements
    private let scrollView = UIScrollView()
    private let contentStack = UIStackView()
    private let titleLabel = UILabel()
    private let cancelButton = UIButton(type: .system)
    private let sendButton = UIButton(type: .system)
    private let previewLabel = UILabel()
    private let textView = UITextView()
    private let chatPickerLabel = UILabel()
    private let chatTableView = UITableView()
    private let activityIndicator = UIActivityIndicatorView(style: .medium)
    private let errorLabel = UILabel()

    struct SharedItem {
        enum ItemType { case url, text, image }
        let type: ItemType
        let text: String?
        let url: URL?
        let imageData: Data?
    }

    struct RecentChat: Codable {
        let id: String
        let title: String?
        let appId: String?
        let lastMessageAt: String?

        var displayTitle: String { title ?? "New Chat" }

        enum CodingKeys: String, CodingKey {
            case id, title
            case appId = "app_id"
            case lastMessageAt = "last_message_at"
        }
    }

    // MARK: - Lifecycle

    override func viewDidLoad() {
        super.viewDidLoad()
        setupUI()
        extractSharedContent()
        loadRecentChats()
    }

    // MARK: - UI Setup

    private func setupUI() {
        view.backgroundColor = .systemBackground

        // Header bar
        let headerStack = UIStackView()
        headerStack.axis = .horizontal
        headerStack.alignment = .center
        headerStack.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(headerStack)

        cancelButton.setTitle("Cancel", for: .normal)
        cancelButton.addTarget(self, action: #selector(cancelTapped), for: .touchUpInside)
        headerStack.addArrangedSubview(cancelButton)

        titleLabel.text = "Share to OpenMates"
        titleLabel.font = .systemFont(ofSize: 17, weight: .semibold)
        titleLabel.textAlignment = .center
        headerStack.addArrangedSubview(titleLabel)

        sendButton.setTitle("Send", for: .normal)
        sendButton.titleLabel?.font = .systemFont(ofSize: 17, weight: .semibold)
        sendButton.addTarget(self, action: #selector(sendTapped), for: .touchUpInside)
        headerStack.addArrangedSubview(sendButton)

        // Content
        scrollView.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(scrollView)

        contentStack.axis = .vertical
        contentStack.spacing = 12
        contentStack.translatesAutoresizingMaskIntoConstraints = false
        scrollView.addSubview(contentStack)

        // Preview
        previewLabel.font = .systemFont(ofSize: 13)
        previewLabel.textColor = .secondaryLabel
        previewLabel.numberOfLines = 3
        contentStack.addArrangedSubview(previewLabel)

        // Message input
        textView.font = .systemFont(ofSize: 15)
        textView.layer.borderColor = UIColor.separator.cgColor
        textView.layer.borderWidth = 0.5
        textView.layer.cornerRadius = 10
        textView.textContainerInset = UIEdgeInsets(top: 12, left: 8, bottom: 12, right: 8)
        textView.placeholder = "Add a message (optional)..."
        let textViewHeight = textView.heightAnchor.constraint(equalToConstant: 100)
        textViewHeight.isActive = true
        contentStack.addArrangedSubview(textView)

        // Chat picker section
        chatPickerLabel.text = "Send to:"
        chatPickerLabel.font = .systemFont(ofSize: 15, weight: .semibold)
        chatPickerLabel.textColor = .label
        contentStack.addArrangedSubview(chatPickerLabel)

        // New Chat option (always first)
        let newChatButton = UIButton(type: .system)
        newChatButton.setTitle("＋ New Chat", for: .normal)
        newChatButton.titleLabel?.font = .systemFont(ofSize: 15, weight: .medium)
        newChatButton.contentHorizontalAlignment = .leading
        newChatButton.contentEdgeInsets = UIEdgeInsets(top: 12, left: 16, bottom: 12, right: 16)
        newChatButton.backgroundColor = .systemGray6
        newChatButton.layer.cornerRadius = 10
        newChatButton.tag = -1
        newChatButton.addTarget(self, action: #selector(newChatTapped), for: .touchUpInside)
        contentStack.addArrangedSubview(newChatButton)
        highlightButton(newChatButton, selected: true)

        // Chat list
        chatTableView.dataSource = self
        chatTableView.delegate = self
        chatTableView.register(ChatCell.self, forCellReuseIdentifier: "ChatCell")
        chatTableView.isScrollEnabled = false
        chatTableView.separatorStyle = .none
        chatTableView.rowHeight = 52
        chatTableView.translatesAutoresizingMaskIntoConstraints = false
        contentStack.addArrangedSubview(chatTableView)

        // Loading indicator
        activityIndicator.hidesWhenStopped = true
        activityIndicator.startAnimating()
        contentStack.addArrangedSubview(activityIndicator)

        // Error
        errorLabel.font = .systemFont(ofSize: 13)
        errorLabel.textColor = .systemRed
        errorLabel.numberOfLines = 0
        errorLabel.textAlignment = .center
        errorLabel.isHidden = true
        contentStack.addArrangedSubview(errorLabel)

        NSLayoutConstraint.activate([
            headerStack.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 8),
            headerStack.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 16),
            headerStack.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -16),

            scrollView.topAnchor.constraint(equalTo: headerStack.bottomAnchor, constant: 16),
            scrollView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            scrollView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            scrollView.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor),

            contentStack.topAnchor.constraint(equalTo: scrollView.topAnchor, constant: 0),
            contentStack.leadingAnchor.constraint(equalTo: scrollView.leadingAnchor, constant: 16),
            contentStack.trailingAnchor.constraint(equalTo: scrollView.trailingAnchor, constant: -16),
            contentStack.bottomAnchor.constraint(equalTo: scrollView.bottomAnchor, constant: -16),
            contentStack.widthAnchor.constraint(equalTo: scrollView.widthAnchor, constant: -32),
        ])
    }

    // MARK: - Extract shared content

    private func extractSharedContent() {
        guard let extensionItems = extensionContext?.inputItems as? [NSExtensionItem] else {
            showError("No content to share")
            return
        }

        let group = DispatchGroup()

        for item in extensionItems {
            guard let attachments = item.attachments else { continue }

            for attachment in attachments {
                if attachment.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
                    group.enter()
                    attachment.loadItem(forTypeIdentifier: UTType.url.identifier) { [weak self] data, _ in
                        if let url = data as? URL {
                            self?.sharedItems.append(SharedItem(type: .url, text: url.absoluteString, url: url, imageData: nil))
                        }
                        group.leave()
                    }
                } else if attachment.hasItemConformingToTypeIdentifier(UTType.plainText.identifier) {
                    group.enter()
                    attachment.loadItem(forTypeIdentifier: UTType.plainText.identifier) { [weak self] data, _ in
                        if let text = data as? String {
                            self?.sharedItems.append(SharedItem(type: .text, text: text, url: nil, imageData: nil))
                        }
                        group.leave()
                    }
                } else if attachment.hasItemConformingToTypeIdentifier(UTType.image.identifier) {
                    group.enter()
                    attachment.loadItem(forTypeIdentifier: UTType.image.identifier) { [weak self] data, _ in
                        var imageData: Data?
                        if let url = data as? URL { imageData = try? Data(contentsOf: url) }
                        else if let image = data as? UIImage { imageData = image.jpegData(compressionQuality: 0.8) }
                        if let imageData { self?.sharedItems.append(SharedItem(type: .image, text: nil, url: nil, imageData: imageData)) }
                        group.leave()
                    }
                }
            }
        }

        group.notify(queue: .main) { [weak self] in self?.updatePreview() }
    }

    private func updatePreview() {
        var previews: [String] = []
        for item in sharedItems {
            switch item.type {
            case .url: previews.append("🔗 \(item.text ?? "")")
            case .text: previews.append("📝 \(String((item.text ?? "").prefix(80)))")
            case .image: previews.append("🖼 Image attachment")
            }
        }
        previewLabel.text = previews.joined(separator: "\n")
    }

    // MARK: - Load recent chats

    private func loadRecentChats() {
        Task {
            do {
                let data = try await apiRequest(.get, path: "/v1/chats?limit=15")
                struct ChatListResponse: Codable { let chats: [RecentChat] }
                let decoded = try JSONDecoder().decode(ChatListResponse.self, from: data)
                await MainActor.run {
                    recentChats = decoded.chats
                    isLoadingChats = false
                    activityIndicator.stopAnimating()
                    let tableHeight = chatTableView.heightAnchor.constraint(equalToConstant: CGFloat(min(recentChats.count, 8)) * 52)
                    tableHeight.isActive = true
                    chatTableView.reloadData()
                }
            } catch {
                await MainActor.run {
                    isLoadingChats = false
                    activityIndicator.stopAnimating()
                    if (error as NSError).code == 401 {
                        showError("Please log in to OpenMates first")
                    }
                }
            }
        }
    }

    // MARK: - Actions

    @objc private func cancelTapped() {
        extensionContext?.completeRequest(returningItems: nil)
    }

    @objc private func newChatTapped() {
        selectedChat = nil
        // Deselect table rows
        if let indexPath = chatTableView.indexPathForSelectedRow {
            chatTableView.deselectRow(at: indexPath, animated: true)
        }
        // Highlight new chat button
        for subview in contentStack.arrangedSubviews where subview.tag == -1 {
            highlightButton(subview as? UIButton, selected: true)
        }
    }

    @objc private func sendTapped() {
        guard !isSubmitting else { return }
        isSubmitting = true
        sendButton.isEnabled = false
        activityIndicator.startAnimating()
        errorLabel.isHidden = true

        Task {
            do {
                try await sendToOpenMates()
                await MainActor.run {
                    extensionContext?.completeRequest(returningItems: nil)
                }
            } catch {
                await MainActor.run {
                    showError(error.localizedDescription)
                    isSubmitting = false
                    sendButton.isEnabled = true
                    activityIndicator.stopAnimating()
                }
            }
        }
    }

    // MARK: - Send to API

    private func sendToOpenMates() async throws {
        var messageContent = textView.text ?? ""

        for item in sharedItems {
            switch item.type {
            case .url, .text:
                if !messageContent.isEmpty { messageContent += "\n\n" }
                messageContent += item.text ?? ""
            case .image:
                if messageContent.isEmpty { messageContent = "Shared image" }
            }
        }

        guard !messageContent.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            throw ShareError.emptyContent
        }

        let chatId: String
        let chatHasTitle: Bool

        if let existing = selectedChat {
            // Send to existing chat
            chatId = existing.id
            chatHasTitle = existing.title != nil
        } else {
            // Create new chat
            chatId = UUID().uuidString
            chatHasTitle = false
        }

        let messageId = UUID().uuidString
        let body: [String: Any] = [
            "chat_id": chatId,
            "message": [
                "message_id": messageId,
                "role": "user",
                "content": messageContent,
                "created_at": Int(Date().timeIntervalSince1970),
                "chat_has_title": chatHasTitle,
            ] as [String: Any],
        ]

        let jsonData = try JSONSerialization.data(withJSONObject: body)
        let _ = try await apiRequest(.post, path: "/v1/chat/message", body: jsonData)

        // Upload images if any
        for item in sharedItems where item.type == .image {
            if let imageData = item.imageData {
                try await uploadImage(imageData, chatId: chatId)
            }
        }
    }

    private func uploadImage(_ data: Data, chatId: String) async throws {
        let boundary = UUID().uuidString
        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"shared-image.jpg\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: image/jpeg\r\n\r\n".data(using: .utf8)!)
        body.append(data)
        body.append("\r\n--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"chat_id\"\r\n\r\n".data(using: .utf8)!)
        body.append(chatId.data(using: .utf8)!)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)

        let baseURL = Self.apiBaseURL
        let url = baseURL.deletingLastPathComponent().appendingPathComponent("upload/v1/files")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.httpBody = body

        let session = Self.sharedSession
        let (_, _) = try await session.data(for: request)
    }

    // MARK: - Networking

    enum HTTPMethod: String { case get = "GET", post = "POST" }

    private static var apiBaseURL: URL {
        #if DEBUG
        URL(string: "https://dev.openmates.org/api")!
        #else
        URL(string: "https://api.openmates.org")!
        #endif
    }

    private static var sharedSession: URLSession = {
        let config = URLSessionConfiguration.default
        config.httpCookieAcceptPolicy = .always
        config.httpShouldSetCookies = true
        config.httpCookieStorage = HTTPCookieStorage.sharedCookieStorage(
            forGroupContainerIdentifier: "group.org.openmates.app"
        )
        return URLSession(configuration: config)
    }()

    private func apiRequest(_ method: HTTPMethod, path: String, body: Data? = nil) async throws -> Data {
        let url = Self.apiBaseURL.appendingPathComponent(path)
        var request = URLRequest(url: url)
        request.httpMethod = method.rawValue
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = body

        let (data, response) = try await Self.sharedSession.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw ShareError.networkError
        }
        if httpResponse.statusCode == 401 { throw ShareError.notAuthenticated }
        guard (200...299).contains(httpResponse.statusCode) else {
            throw ShareError.serverError(httpResponse.statusCode)
        }
        return data
    }

    // MARK: - Helpers

    private func showError(_ message: String) {
        errorLabel.text = message
        errorLabel.isHidden = false
    }

    private func highlightButton(_ button: UIButton?, selected: Bool) {
        button?.backgroundColor = selected ? .systemBlue.withAlphaComponent(0.12) : .systemGray6
        button?.layer.borderWidth = selected ? 1.5 : 0
        button?.layer.borderColor = selected ? UIColor.systemBlue.cgColor : nil
    }
}

// MARK: - Chat list data source + delegate

extension ShareViewController: UITableViewDataSource, UITableViewDelegate {
    func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int {
        recentChats.count
    }

    func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let cell = tableView.dequeueReusableCell(withIdentifier: "ChatCell", for: indexPath) as! ChatCell
        let chat = recentChats[indexPath.row]
        cell.configure(title: chat.displayTitle, appId: chat.appId)
        return cell
    }

    func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        selectedChat = recentChats[indexPath.row]
        // Unhighlight new chat button
        for subview in contentStack.arrangedSubviews where subview.tag == -1 {
            highlightButton(subview as? UIButton, selected: false)
        }
    }
}

// MARK: - Chat cell

class ChatCell: UITableViewCell {
    private let iconView = UIView()
    private let titleView = UILabel()

    override init(style: UITableViewCell.CellStyle, reuseIdentifier: String?) {
        super.init(style: style, reuseIdentifier: reuseIdentifier)

        iconView.layer.cornerRadius = 16
        iconView.clipsToBounds = true
        iconView.translatesAutoresizingMaskIntoConstraints = false
        contentView.addSubview(iconView)

        titleView.font = .systemFont(ofSize: 15)
        titleView.translatesAutoresizingMaskIntoConstraints = false
        contentView.addSubview(titleView)

        NSLayoutConstraint.activate([
            iconView.leadingAnchor.constraint(equalTo: contentView.leadingAnchor, constant: 12),
            iconView.centerYAnchor.constraint(equalTo: contentView.centerYAnchor),
            iconView.widthAnchor.constraint(equalToConstant: 32),
            iconView.heightAnchor.constraint(equalToConstant: 32),

            titleView.leadingAnchor.constraint(equalTo: iconView.trailingAnchor, constant: 12),
            titleView.trailingAnchor.constraint(equalTo: contentView.trailingAnchor, constant: -12),
            titleView.centerYAnchor.constraint(equalTo: contentView.centerYAnchor),
        ])
    }

    required init?(coder: NSCoder) { fatalError() }

    func configure(title: String, appId: String?) {
        titleView.text = title
        iconView.backgroundColor = .systemBlue.withAlphaComponent(0.15)
    }
}

// MARK: - Errors

enum ShareError: LocalizedError {
    case emptyContent, notAuthenticated, networkError, serverError(Int)

    var errorDescription: String? {
        switch self {
        case .emptyContent: return "Nothing to share"
        case .notAuthenticated: return "Please log in to OpenMates first"
        case .networkError: return "Network error — check your connection"
        case .serverError(let code): return "Server error (\(code))"
        }
    }
}

// MARK: - UITextView placeholder

extension UITextView {
    var placeholder: String? {
        get { layer.value(forKey: "placeholder") as? String }
        set {
            guard let text = newValue else { return }
            let label = UILabel()
            label.text = text
            label.font = font
            label.textColor = .placeholderText
            label.tag = 999
            label.translatesAutoresizingMaskIntoConstraints = false
            addSubview(label)
            NSLayoutConstraint.activate([
                label.topAnchor.constraint(equalTo: topAnchor, constant: textContainerInset.top),
                label.leadingAnchor.constraint(equalTo: leadingAnchor, constant: textContainerInset.left + textContainer.lineFragmentPadding),
            ])
            NotificationCenter.default.addObserver(forName: UITextView.textDidChangeNotification, object: self, queue: .main) { [weak self] _ in
                self?.viewWithTag(999)?.isHidden = !(self?.text.isEmpty ?? true)
            }
        }
    }
}
