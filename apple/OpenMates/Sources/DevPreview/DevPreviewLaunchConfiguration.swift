// Debug-only isolated component routing and fixture configuration.
// URL, environment, and launch arguments resolve to the same value identity.
// Invalid requested previews remain previews with a visible configuration error;
// they must never fall through to account restoration or normal product startup.
// Registry metadata describes intended production renderers, not parity approval.
// Release builds do not compile this configuration or expose preview routes.
//
// ─── Web source ─────────────────────────────────────────────────────
// Svelte: frontend/apps/web_app/src/routes/dev/preview/[...path]/+page.svelte
//         frontend/apps/web_app/src/routes/dev/preview/embeds/[app=embedApp]/+page.svelte
// ────────────────────────────────────────────────────────────────────

#if DEBUG
import Foundation

/// JSON values only: fixture props cannot carry executable callbacks or services.
indirect enum DevPreviewJSONValue: Codable, Hashable {
    case null
    case bool(Bool)
    case number(Double)
    case string(String)
    case array([DevPreviewJSONValue])
    case object([String: DevPreviewJSONValue])

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null }
        else if let value = try? container.decode(Bool.self) { self = .bool(value) }
        else if let value = try? container.decode(Double.self) { self = .number(value) }
        else if let value = try? container.decode(String.self) { self = .string(value) }
        else if let value = try? container.decode([DevPreviewJSONValue].self) { self = .array(value) }
        else { self = .object(try container.decode([String: DevPreviewJSONValue].self)) }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .null: try container.encodeNil()
        case .bool(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .string(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        }
    }

    var string: String? { if case .string(let value) = self { value } else { nil } }
    var bool: Bool? { if case .bool(let value) = self { value } else { nil } }
    var double: Double? { if case .number(let value) = self { value } else { nil } }
    var int: Int? {
        guard let value = double, value.isFinite else { return nil }
        return Int(exactly: value)
    }
    var object: [String: DevPreviewJSONValue]? { if case .object(let value) = self { value } else { nil } }
    var array: [DevPreviewJSONValue]? { if case .array(let value) = self { value } else { nil } }

    fileprivate func isBounded(depth: Int = 0) -> Bool {
        guard depth <= 8 else { return false }
        switch self {
        case .number(let value): return value.isFinite
        case .array(let values): return values.count <= 200 && values.allSatisfy { $0.isBounded(depth: depth + 1) }
        case .object(let values): return values.count <= 100 && values.allSatisfy { $0.key.count <= 100 && $0.value.isBounded(depth: depth + 1) }
        default: return true
        }
    }
}

enum DevPreviewComponent: String, CaseIterable, Hashable {
    case composer
    case chatHeader = "chat-header"
    case message
    case embedPreview = "embed-preview"
    case embedFullscreen = "embed-fullscreen"
    case history
    case sidebar
    case welcome
    case login
    case signup

    var descriptor: DevPreviewComponentDescriptor { DevPreviewComponentRegistry.descriptor(for: self) }
}

struct DevPreviewComponentDescriptor: Hashable {
    enum HostSupport: Hashable {
        /// The component host must render its production view and local actions.
        case componentHost
        /// Selection is recognized, but no isolated implementation is advertised.
        case planned
    }
    let component: DevPreviewComponent
    let webComponentPath: String
    let nativeRendererNames: [String]
    let variants: [String]
    let hostSupport: HostSupport

    var webPreviewURL: URL {
        // These paths are static registry data; no caller-provided host is used.
        URL(string: "https://app.dev.openmates.org/dev/preview/\(webComponentPath)?chrome=0")!
    }
}

enum DevPreviewComponentRegistry {
    static func descriptor(for component: DevPreviewComponent) -> DevPreviewComponentDescriptor {
        switch component {
        case .composer:
            return .init(component: component, webComponentPath: "enter_message/MessageInput", nativeRendererNames: ["MessageComposerView", "NativeComposerSession"], variants: ["model", "default", "focused", "filled", "attachment", "disabled"], hostSupport: .componentHost)
        case .chatHeader:
            return .init(component: component, webComponentPath: "ChatHeader", nativeRendererNames: ["ChatBannerView"], variants: ["default", "loading", "incognito", "draft", "long-title"], hostSupport: .componentHost)
        case .message:
            return .init(component: component, webComponentPath: "ChatMessage", nativeRendererNames: ["MessageBubble"], variants: ["default", "user", "assistant", "thinking", "markdown", "citations", "streaming", "streaming-long", "streaming-reduced-motion"], hostSupport: .componentHost)
        case .embedPreview:
            return .init(component: component, webComponentPath: "embeds/web/WebSearchEmbedPreview", nativeRendererNames: ["EmbedPreviewCard"], variants: ["default", "processing", "error", "cancelled"], hostSupport: .componentHost)
        case .embedFullscreen:
            return .init(component: component, webComponentPath: "embeds/web/WebSearchEmbedFullscreen", nativeRendererNames: ["EmbedFullscreenContainer"], variants: ["default", "processing", "error", "withNavigation", "actions-code"], hostSupport: .componentHost)
        case .sidebar:
            return .init(component: component, webComponentPath: "chats/Chats", nativeRendererNames: ["ChatSidebarContent", "ChatListRow", "ChatSearchView"], variants: ["default", "guest", "account", "empty", "dated"], hostSupport: .componentHost)
        case .history:
            return .init(component: component, webComponentPath: "ChatHistory", nativeRendererNames: ["ChatView", "MessageBubble"], variants: ["default", "long", "mixed", "workspace"], hostSupport: .componentHost)
        case .welcome:
            return .init(component: component, webComponentPath: "ActiveChat", nativeRendererNames: ["WelcomeContinuationCarousel"], variants: ["default", "empty", "continuation"], hostSupport: .componentHost)
        case .login:
            return .init(component: component, webComponentPath: "Login", nativeRendererNames: ["AuthLoginHeading", "EmailLookupForm", "PasswordLoginForm"], variants: ["default", "email", "password", "otp", "error", "lookup-error", "password-error"], hostSupport: .componentHost)
        case .signup:
            return .init(component: component, webComponentPath: "signup/Signup", nativeRendererNames: ["NativeSignupForm", "SignupBasicsFormView", "SignupConfirmEmailStep", "SignupPasswordStep"], variants: ["default", "basics", "error", "loading", "unavailable", "confirm-email", "secure-account", "password", "creation-uncertain", "passkey", "passkey-prf-error", "passkey-cancel", "passkey-uncertain"], hostSupport: .componentHost)
        }
    }

    static func component(for route: String) -> DevPreviewComponent? {
        if let component = DevPreviewComponent(rawValue: route) { return component }
        return DevPreviewComponent.allCases.first { $0.descriptor.webComponentPath == route }
    }
}

struct DevPreviewLaunchConfiguration: Hashable {
    enum Surface: String, Hashable {
        case chatOpening = "chat-opening"
        case chatOpeningRecording = "chat-opening-recording"
        case chatShare = "chat-share"
        case embedShare = "embed-share"
        case quickCapture = "quick-capture"
        case composerEmbeds = "composer-embeds"
        case composerDraftEdit = "composer-draft-edit"
        case embeds
        case component
    }
    enum Theme: String, Hashable { case system, light, dark }

    let surface: Surface
    let appSlug: DevEmbedPreviewApp
    let component: DevPreviewComponent?
    let variant: String
    let theme: Theme
    let width: Int?
    let height: Int?
    let props: [String: DevPreviewJSONValue]
    let error: String?

    init(surface: Surface, appSlug: DevEmbedPreviewApp = .web, component: DevPreviewComponent? = nil, variant: String = "default", theme: Theme = .system, width: Int? = nil, height: Int? = nil, props: [String: DevPreviewJSONValue] = [:], error: String? = nil) {
        self.surface = surface
        self.appSlug = appSlug
        self.component = component
        self.variant = variant
        self.theme = theme
        self.width = width
        self.height = height
        self.props = props
        self.error = error
    }

    func decodeProps<T: Decodable>(_ type: T.Type) throws -> T {
        try JSONDecoder().decode(type, from: JSONEncoder().encode(props))
    }

    static var current: DevPreviewLaunchConfiguration? {
        parse(environment: ProcessInfo.processInfo.environment)
            ?? parse(arguments: ProcessInfo.processInfo.arguments)
    }

    private static let optionNames = ["app", "component", "variant", "theme", "width", "height", "props"]
    private static let maximumPropsBytes = 10_000

    static func parse(environment: [String: String]) -> DevPreviewLaunchConfiguration? {
        let hasRequest = environment.keys.contains { $0 == "DEV_PREVIEW" || $0.hasPrefix("DEV_PREVIEW_") }
        guard hasRequest else { return nil }
        let knownNames = Set(["DEV_PREVIEW", "DEV_PREVIEW_URL"] + optionNames.map { "DEV_PREVIEW_\($0.uppercased())" })
        guard !environment.keys.contains(where: { $0.hasPrefix("DEV_PREVIEW_") && !knownNames.contains($0) }) else { return invalid("Unknown preview environment option.") }
        if let rawURL = environment["DEV_PREVIEW_URL"] {
            guard environment["DEV_PREVIEW"] == nil,
                  !optionNames.contains(where: { environment["DEV_PREVIEW_\($0.uppercased())"] != nil }) else {
                return invalid("Use either DEV_PREVIEW_URL or individual preview options.")
            }
            guard let url = URL(string: rawURL), let parsed = parse(url: url) else { return invalid("Invalid preview URL.") }
            return parsed
        }
        let options = Dictionary(uniqueKeysWithValues: optionNames.compactMap { name in
            environment["DEV_PREVIEW_\(name.uppercased())"].map { (name, $0) }
        })
        return resolve(route: environment["DEV_PREVIEW"] ?? "component", options: options)
    }

    static func parse(arguments: [String]) -> DevPreviewLaunchConfiguration? {
        guard arguments.contains(where: { $0 == "--dev-preview" || $0.hasPrefix("--dev-preview-") }) else { return nil }
        let knownFlags = Set(["--dev-preview", "--dev-preview-url"] + optionNames.map { "--dev-preview-\($0)" })
        var values: [String: String] = [:]
        var index = 0
        while index < arguments.count {
            let flag = arguments[index]
            guard flag == "--dev-preview" || flag.hasPrefix("--dev-preview-") else { index += 1; continue }
            guard knownFlags.contains(flag) else { return invalid("Unknown preview launch option.") }
            guard values[flag] == nil else { return invalid("Duplicate preview launch option.") }
            guard index + 1 < arguments.count, !arguments[index + 1].hasPrefix("--") else { return invalid("A preview launch option is missing its value.") }
            values[flag] = arguments[index + 1]
            index += 2
        }
        if let rawURL = values["--dev-preview-url"] {
            guard values.count == 1 else { return invalid("Use either --dev-preview-url or individual preview options.") }
            guard let url = URL(string: rawURL), let parsed = parse(url: url) else { return invalid("Invalid preview URL.") }
            return parsed
        }
        let options = Dictionary(uniqueKeysWithValues: optionNames.compactMap { name in
            values["--dev-preview-\(name)"].map { (name, $0) }
        })
        return resolve(route: values["--dev-preview"] ?? "component", options: options)
    }

    static func parse(url: URL) -> DevPreviewLaunchConfiguration? {
        // URL.path removes a trailing slash on Apple Foundation, which would
        // silently admit non-exact routes such as /preview/composer/.
        // URLComponents preserves it for validation before route resolution.
        let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        let path = components?.path ?? url.path
        let isNative = url.scheme?.lowercased() == "openmates" && url.host?.lowercased() == "dev"
        let isNativePreviewPath = url.scheme?.lowercased() == "openmates" && (path == "/preview" || path.hasPrefix("/preview/"))
        let isWebPreview = path == "/dev/preview" || path.hasPrefix("/dev/preview/")
        guard isNative || isNativePreviewPath || isWebPreview else { return nil }
        guard url.user == nil, url.password == nil, url.fragment == nil else { return invalid("Preview URLs cannot include credentials or a fragment.") }
        let host = url.host?.lowercased() ?? ""
        let scheme = url.scheme?.lowercased() ?? ""
        let allowedWebOrigin = (scheme == "https" && host == "app.dev.openmates.org" && (url.port == nil || url.port == 443))
            || (["http", "https"].contains(scheme) && ["localhost", "127.0.0.1", "[::1]", "::1"].contains(host))
        guard isNative ? url.port == nil : allowedWebOrigin else { return invalid("Preview URL origin is not an allowed development origin.") }
        let prefix = isNative ? "/preview/" : "/dev/preview/"
        guard path.hasPrefix(prefix) else { return invalid("Preview URL is missing a component or legacy surface.") }
        let route = String(path.dropFirst(prefix.count))
        guard !route.isEmpty, !route.hasSuffix("/"), !route.contains("//") else { return invalid("Preview route must exactly identify one component or legacy surface.") }
        var options: [String: String] = [:]
        for item in components?.queryItems ?? [] {
            guard (optionNames + ["chrome"]).contains(item.name) else { return invalid("Unknown preview URL option.") }
            guard options[item.name] == nil, let value = item.value else { return invalid("Duplicate or missing preview URL option.") }
            options[item.name] = value
        }
        if let chrome = options.removeValue(forKey: "chrome"), chrome != "0" { return invalid("Isolated component previews require chrome=0.") }
        return resolve(route: route, options: options)
    }

    private static func resolve(route: String, options: [String: String]) -> DevPreviewLaunchConfiguration {
        let parts = route.split(separator: "/", omittingEmptySubsequences: false).map(String.init)
        let surface: Surface
        let component: DevPreviewComponent?
        var routeApp: String?
        if parts.first == "component" {
            guard parts.count <= 2 else { return invalid("Unknown component route.") }
            let componentName = parts.count == 2 ? parts[1] : options["component"]
            guard let componentName, let knownComponent = DevPreviewComponentRegistry.component(for: componentName) else { return invalid("Unknown preview component.") }
            guard options["component"] == nil || options["component"] == knownComponent.rawValue else { return invalid("Conflicting preview component options.") }
            surface = .component
            component = knownComponent
        } else if let knownComponent = DevPreviewComponentRegistry.component(for: route) {
            guard options["component"] == nil || options["component"] == knownComponent.rawValue else { return invalid("Conflicting preview component options.") }
            surface = .component
            component = knownComponent
        } else if let legacySurface = Surface(rawValue: route), legacySurface != .component {
            guard options["component"] == nil else { return invalid("A legacy preview cannot select an isolated component.") }
            surface = legacySurface
            component = nil
        } else if parts.count == 2, parts[0] == "embeds" {
            guard options["component"] == nil else { return invalid("A legacy preview cannot select an isolated component.") }
            surface = .embeds
            component = nil
            routeApp = parts[1]
        } else {
            return invalid("Unknown preview route.")
        }
        guard routeApp == nil || options["app"] == nil || routeApp == options["app"] else { return invalid("Conflicting preview app options.") }
        guard let app = DevEmbedPreviewApp(rawValue: routeApp ?? options["app"] ?? "web") else { return invalid("Unknown embed preview app.") }
        guard let theme = Theme(rawValue: options["theme"] ?? "system") else { return invalid("Unknown preview theme.") }
        let variant = options["variant"] ?? "default"
        guard (component?.descriptor.variants ?? ["default"]).contains(variant) else { return invalid("Unknown variant for the selected preview.") }
        var dimensions: [String: Int] = [:]
        for name in ["width", "height"] {
            if let raw = options[name] {
                guard let value = Int(raw), (240...2_560).contains(value) else { return invalid("Preview viewport dimensions must be integers from 240 to 2560.") }
                dimensions[name] = value
            }
        }
        var props: [String: DevPreviewJSONValue] = [:]
        if let raw = options["props"] {
            guard let data = raw.data(using: .utf8), data.count <= maximumPropsBytes else { return invalid("Preview props exceed the 10000-byte limit.") }
            guard let value = try? JSONDecoder().decode(DevPreviewJSONValue.self, from: data), let object = value.object, value.isBounded() else { return invalid("Preview props must be a bounded JSON object.") }
            props = object
        }
        let error: String? = component?.descriptor.hostSupport == .planned
            ? "This component is registered for future isolated preview support; it is not implemented yet."
            : nil
        return .init(surface: surface, appSlug: app, component: component, variant: variant, theme: theme, width: dimensions["width"], height: dimensions["height"], props: props, error: error)
    }

    private static func invalid(_ message: String) -> DevPreviewLaunchConfiguration {
        .init(surface: .component, error: message)
    }
}
#endif
