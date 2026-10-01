import Foundation

/// Client-side protection for hosted Project files. Private patterns are
/// additive; malformed controls fail the whole operation before file content
/// can be returned. This policy is independent of Project display metadata.
struct ProjectHostedPathPolicy {
    struct IgnoreFile {
        let path: String
        let content: String
    }

    enum Failure: Error { case protectedPath }

    private struct Rule {
        let scope: String
        let regex: NSRegularExpression
        let negated: Bool
    }

    private let privateRules: [Rule]
    private let ignoreRules: [Rule]

    init(ignoreFiles: [IgnoreFile], privatePaths: [String]) throws {
        guard ignoreFiles.count <= 64, privatePaths.count <= 256 else { throw Failure.protectedPath }
        privateRules = try (Self.builtinPrivatePaths + privatePaths).map {
            try Self.rule($0, scope: "", privateRule: true)
        }
        var rules: [Rule] = []
        let controls = ignoreFiles.sorted { lhs, rhs in
            let leftDepth = lhs.path.split(separator: "/").count
            let rightDepth = rhs.path.split(separator: "/").count
            return leftDepth == rightDepth ? lhs.path < rhs.path : leftDepth < rightDepth
        }
        guard Set(controls.map(\.path)).count == controls.count else { throw Failure.protectedPath }
        for file in controls {
            guard file.path == ".gitignore" || file.path.hasSuffix("/.gitignore"),
                  file.content.utf8.count <= 64 * 1024 else { throw Failure.protectedPath }
            let scope = file.path == ".gitignore" ? "" : String(file.path.dropLast("/.gitignore".count))
            for line in file.content.components(separatedBy: .newlines) {
                if line.isEmpty || line.hasPrefix("#") { continue }
                rules.append(try Self.rule(line, scope: scope, privateRule: false))
            }
        }
        ignoreRules = rules
    }

    func isPrivate(_ path: String) -> Bool {
        guard Self.normalized(path) != nil else { return true }
        return privateRules.contains { $0.regex.firstMatch(in: path,
            range: NSRange(path.startIndex..<path.endIndex, in: path)) != nil }
    }

    func isIgnored(_ path: String) -> Bool {
        guard Self.normalized(path) != nil else { return true }
        let components = path.split(separator: "/")
        if components.count > 1 {
            for count in 1..<components.count {
                if ignoredByRules(components.prefix(count).joined(separator: "/")) { return true }
            }
        }
        return ignoredByRules(path)
    }

    private func ignoredByRules(_ path: String) -> Bool {
        var ignored = false
        for rule in ignoreRules {
            guard rule.scope.isEmpty || path.hasPrefix(rule.scope + "/") else { continue }
            let relative = rule.scope.isEmpty ? path : String(path.dropFirst(rule.scope.count + 1))
            let matched = rule.regex.firstMatch(in: relative,
                range: NSRange(relative.startIndex..<relative.endIndex, in: relative)) != nil
            if matched { ignored = !rule.negated }
        }
        return ignored
    }

    static func normalized(_ raw: String) -> String? {
        guard raw.utf8.count <= 4096, ProjectWorkspacePath.normalized(raw) != nil,
              !raw.split(separator: "/").contains(".git"),
              !raw.split(separator: "/").contains(".openmates-private-path-probe") else { return nil }
        return raw
    }

    private static func rule(_ source: String, scope: String, privateRule: Bool) throws -> Rule {
        guard !source.isEmpty, !source.contains("\\"),
              source.last?.isWhitespace == false,
              !source.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 }),
              source.utf8.count <= 4096 else { throw Failure.protectedPath }
        var text = source
        let negated = !privateRule && text.hasPrefix("!")
        if negated { text.removeFirst() }
        guard !text.isEmpty, !text.contains("["), !text.contains("]"),
              !text.split(separator: "/").contains(".."),
              !privateRule || !text.hasPrefix("!") else { throw Failure.protectedPath }
        let anchored = text.hasPrefix("/")
        if anchored { text.removeFirst() }
        let directory = text.hasSuffix("/")
        if directory { text.removeLast() }
        guard !text.isEmpty else { throw Failure.protectedPath }

        var regex = ""
        let characters = Array(text)
        var index = 0
        while index < characters.count {
            let character = characters[index]
            if character == "*" {
                if index + 1 < characters.count && characters[index + 1] == "*" {
                    index += 1
                    if index + 1 < characters.count && characters[index + 1] == "/" {
                        regex += "(?:.*/)?"
                        index += 1
                    } else { regex += ".*" }
                } else { regex += "[^/]*" }
            } else if character == "?" { regex += "[^/]" }
            else if ".+(){}^$|\\".contains(character) { regex += "\\" + String(character) }
            else { regex.append(character) }
            index += 1
        }
        let hasSlash = text.contains("/")
        let prefix = anchored || hasSlash ? "^" : "(?:^|.*/)"
        let suffix = directory ? "(?:/.*)?$" : "$"
        // The web `ignore` package defaults to case-insensitive matching for
        // private patterns, while repository .gitignore files opt out of it.
        let options: NSRegularExpression.Options = privateRule ? [.caseInsensitive] : []
        return Rule(scope: scope, regex: try NSRegularExpression(pattern: prefix + regex + suffix,
            options: options),
            negated: negated)
    }

    /// The same bounded *, ** and ? grammar as projectSearchProtocol.ts.
    static func matchesSearchGlob(_ path: String, glob: String?) -> Bool {
        guard let glob else { return true }
        let pathChars = Array(path)
        let globChars = Array(glob)
        struct Position: Hashable { let path: Int; let glob: Int }
        var memo: [Position: Bool] = [:]
        func visit(_ p: Int, _ g: Int) -> Bool {
            let key = Position(path: p, glob: g)
            if let cached = memo[key] { return cached }
            let matched: Bool
            if g == globChars.count {
                matched = p == pathChars.count
            } else if g + 2 < globChars.count && globChars[g] == "*" &&
                        globChars[g + 1] == "*" && globChars[g + 2] == "/" {
                var found = visit(p, g + 3)
                if !found && p < pathChars.count {
                    for index in p..<pathChars.count where pathChars[index] == "/" {
                        if visit(index + 1, g + 3) { found = true; break }
                    }
                }
                matched = found
            } else if g + 1 < globChars.count && globChars[g] == "*" && globChars[g + 1] == "*" {
                matched = visit(p, g + 2) || (p < pathChars.count && visit(p + 1, g))
            } else if globChars[g] == "*" {
                matched = visit(p, g + 1) || (p < pathChars.count && pathChars[p] != "/" && visit(p + 1, g))
            } else if globChars[g] == "?" {
                matched = p < pathChars.count && pathChars[p] != "/" && visit(p + 1, g + 1)
            } else {
                matched = p < pathChars.count && pathChars[p] == globChars[g] && visit(p + 1, g + 1)
            }
            memo[key] = matched
            return matched
        }
        return visit(0, 0)
    }

    private static let builtinPrivatePaths: [String] = [
        ".env", ".env.*", "**/.env", "**/.env.*", ".ssh/**", "**/.ssh/**",
        ".aws/**", "**/.aws/**", ".gnupg/**", "**/.gnupg/**",
        ".config/gcloud/**", "**/.config/gcloud/**",
        ".npmrc", "**/.npmrc", ".pypirc", "**/.pypirc", ".netrc", "**/.netrc",
        ".pgpass", "**/.pgpass", ".my.cnf", "**/.my.cnf",
        ".git-credentials", "**/.git-credentials", "credentials", "**/credentials",
        "credentials.json", "**/credentials.json",
        "application_default_credentials.json", "**/application_default_credentials.json",
        "id_rsa", "**/id_rsa", "id_ed25519", "**/id_ed25519", "id_dsa", "**/id_dsa",
        "id_ecdsa", "**/id_ecdsa", "*.pem", "**/*.pem", "*.key", "**/*.key",
        "*.p12", "**/*.p12", "*.pfx", "**/*.pfx", "*.keystore", "**/*.keystore",
        "*.kdbx", "**/*.kdbx", "*.credentials", "**/*.credentials",
        ".openmates/permissions.yml", "**/.openmates/permissions.yml"
    ]
}
