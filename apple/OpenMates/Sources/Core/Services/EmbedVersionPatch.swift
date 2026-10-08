// Exact bounded version patch replay, matching the shared web/CLI reader.
// Specification: specifications/architecture/storage-lifecycle/specification.yml
// Assertions: storage.versions.bounded-reconstruction
import Foundation

enum EmbedVersionPatch {
    static func apply(_ patch: String, to content: String) throws -> String {
        guard !patch.isEmpty, !patch.contains("\0"), patch.utf8.count <= EmbedVersionReconstruction.maximumContentBytes else {
            throw EmbedVersionHistoryFailure.invalidResponse
        }
        var lines = patch.components(separatedBy: "\n")
        if lines.last == "" { lines.removeLast() }
        var index = 0
        if lines.first?.hasPrefix("--- ") == true {
            guard lines.count >= 2, lines[1].hasPrefix("+++ ") else { throw EmbedVersionHistoryFailure.invalidResponse }
            index = 2
        }
        if patch.contains("\\ No newline at end of file") {
            // File header paths are reconstruction labels and confer no authority.
            let normalized = (["--- a/version", "+++ b/version"] + lines.dropFirst(index) + [""]).joined(separator: "\n")
            return try EmbedVersionExactPatch.apply(normalized, to: content, path: "version")
        }
        let source = content.isEmpty ? [] : content.components(separatedBy: "\n")
        var output: [String] = []; var sourceIndex = 0; var hunkCount = 0
        let regex = try NSRegularExpression(pattern: #"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$"#)
        while index < lines.count {
            let header = lines[index]
            guard let match = regex.firstMatch(in: header, range: NSRange(header.startIndex..<header.endIndex, in: header)) else {
                throw EmbedVersionHistoryFailure.invalidResponse
            }
            func number(_ group: Int, default fallback: Int? = nil) throws -> Int {
                guard let range = Range(match.range(at: group), in: header) else {
                    if let fallback { return fallback }; throw EmbedVersionHistoryFailure.invalidResponse
                }
                guard let value = Int(header[range]), value <= Int.max - 1 else { throw EmbedVersionHistoryFailure.invalidResponse }
                return value
            }
            let oldStart = try number(1), oldCount = try number(2, default: 1)
            let newStart = try number(3), newCount = try number(4, default: 1)
            let start = oldCount == 0 ? oldStart : oldStart - 1
            let outputStart = newCount == 0 ? newStart : newStart - 1
            guard start >= sourceIndex, start <= source.count else { throw EmbedVersionHistoryFailure.invalidResponse }
            output.append(contentsOf: source[sourceIndex..<start])
            guard output.count == outputStart else { throw EmbedVersionHistoryFailure.invalidResponse }
            sourceIndex = start; var removed = 0; var added = 0; index += 1
            while index < lines.count, !lines[index].hasPrefix("@@ ") {
                let line = lines[index]
                guard let kind = line.first, kind == " " || kind == "-" || kind == "+" else {
                    throw EmbedVersionHistoryFailure.invalidResponse
                }
                let text = String(line.dropFirst())
                if kind != "+" {
                    guard sourceIndex < source.count, source[sourceIndex] == text else { throw EmbedVersionHistoryFailure.invalidResponse }
                    sourceIndex += 1; removed += 1
                }
                if kind != "-" { output.append(text); added += 1 }
                index += 1
            }
            guard removed == oldCount, added == newCount else { throw EmbedVersionHistoryFailure.invalidResponse }
            hunkCount += 1
        }
        guard hunkCount > 0 else { throw EmbedVersionHistoryFailure.invalidResponse }
        output.append(contentsOf: source.dropFirst(sourceIndex))
        return output.joined(separator: "\n")
    }
}

private enum EmbedVersionExactPatch {
    enum Failure: Error { case invalid }

    private struct Line {
        let value: String
        var hasNewline: Bool
    }
    private struct Row {
        let kind: Character
        var line: Line
    }
    private struct Hunk {
        let oldStart: Int
        let oldCount: Int
        let newStart: Int
        let newCount: Int
        let rows: [Row]
    }

    static func apply(_ diff: String, to original: String, path: String) throws -> String {
        guard !diff.isEmpty, !diff.contains("\0"), !diff.contains("\r") else { throw Failure.invalid }
        var rows = diff.components(separatedBy: "\n")
        if rows.last == "" { rows.removeLast() }
        guard rows.count >= 3,
              let oldPath = header(rows[0], prefix: "--- "),
              let newPath = header(rows[1], prefix: "+++ "),
              oldPath == path, newPath == path else { throw Failure.invalid }

        var hunks: [Hunk] = []
        var index = 2
        while index < rows.count {
            let coordinates = try hunkCoordinates(rows[index])
            index += 1
            var hunkRows: [Row] = []
            var oldSeen = 0
            var newSeen = 0
            while index < rows.count && !rows[index].hasPrefix("@@ ") {
                let text = rows[index]
                if text == "\\ No newline at end of file" {
                    guard !hunkRows.isEmpty, hunkRows[hunkRows.count - 1].line.hasNewline else {
                        throw Failure.invalid
                    }
                    hunkRows[hunkRows.count - 1].line.hasNewline = false
                    index += 1
                    continue
                }
                guard let kind = text.first, kind == " " || kind == "-" || kind == "+" else {
                    throw Failure.invalid
                }
                hunkRows.append(Row(kind: kind, line: Line(value: String(text.dropFirst()), hasNewline: true)))
                if kind != "+" { oldSeen += 1 }
                if kind != "-" { newSeen += 1 }
                index += 1
            }
            guard oldSeen == coordinates.1, newSeen == coordinates.3 else { throw Failure.invalid }
            hunks.append(Hunk(oldStart: coordinates.0, oldCount: coordinates.1,
                              newStart: coordinates.2, newCount: coordinates.3, rows: hunkRows))
        }
        guard !hunks.isEmpty else { throw Failure.invalid }

        let source = split(original)
        var output: [Line] = []
        var sourceIndex = 0
        var outputLine = 1
        for hunk in hunks {
            let expectedSource = hunk.oldCount == 0 ? hunk.oldStart : hunk.oldStart - 1
            let expectedOutput = hunk.newCount == 0 ? hunk.newStart + 1 : hunk.newStart
            guard expectedSource >= sourceIndex, expectedSource <= source.count else { throw Failure.invalid }
            while sourceIndex < expectedSource {
                output.append(source[sourceIndex])
                sourceIndex += 1
                outputLine += 1
            }
            guard outputLine == expectedOutput else { throw Failure.invalid }
            for row in hunk.rows {
                if row.kind != "+" {
                    guard sourceIndex < source.count,
                          source[sourceIndex].value == row.line.value,
                          source[sourceIndex].hasNewline == row.line.hasNewline else {
                        throw Failure.invalid
                    }
                    sourceIndex += 1
                }
                if row.kind != "-" {
                    output.append(row.line)
                    outputLine += 1
                }
            }
        }
        output.append(contentsOf: source.dropFirst(sourceIndex))
        guard output.dropLast().allSatisfy(\.hasNewline) else { throw Failure.invalid }
        return output.map { $0.value + ($0.hasNewline ? "\n" : "") }.joined()
    }

    private static func header(_ text: String, prefix: String) -> String? {
        guard text.hasPrefix(prefix) else { return nil }
        let raw = String(text.dropFirst(prefix.count)).split(separator: "\t", maxSplits: 1,
            omittingEmptySubsequences: false).first.map(String.init) ?? ""
        guard !raw.isEmpty, raw != "/dev/null" else { return nil }
        if raw.hasPrefix("a/") || raw.hasPrefix("b/") { return String(raw.dropFirst(2)) }
        return raw
    }

    private static func hunkCoordinates(_ text: String) throws -> (Int, Int, Int, Int) {
        let pattern = #"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$"#
        let regex = try NSRegularExpression(pattern: pattern)
        let fullRange = NSRange(text.startIndex..<text.endIndex, in: text)
        guard let match = regex.firstMatch(in: text, range: fullRange),
              let oldStart = number(match, 1, in: text),
              let newStart = number(match, 3, in: text) else { throw Failure.invalid }
        let oldCount = number(match, 2, in: text) ?? 1
        let newCount = number(match, 4, in: text) ?? 1
        return (oldStart, oldCount, newStart, newCount)
    }

    private static func number(_ match: NSTextCheckingResult, _ group: Int, in text: String) -> Int? {
        guard let range = Range(match.range(at: group), in: text) else { return nil }
        return Int(text[range])
    }

    private static func split(_ content: String) -> [Line] {
        guard !content.isEmpty else { return [] }
        var lines = content.components(separatedBy: "\n")
        let trailingNewline = lines.last == ""
        if trailingNewline { lines.removeLast() }
        return lines.enumerated().map { index, value in
            Line(value: value, hasNewline: index < lines.count - 1 || trailingNewline)
        }
    }
}
