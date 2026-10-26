/// Internal span with UTF-16 offsets into the source string (matches the
/// JavaScript/Python reference pipeline's indexing so all ports agree exactly).
struct Span {
    var start: Int
    var end: Int
    var label: String
    var score: Double

    init(_ start: Int, _ end: Int, _ label: String, _ score: Double = 1.0) {
        self.start = start; self.end = end; self.label = label; self.score = score
    }
}

/// UTF-16-indexed view over a string, providing the small set of operations
/// the pipeline needs (character access, slicing, whitespace/word tests,
/// literal search). Pure Swift, identical on every platform.
struct UTF16Text {
    let string: String
    private let units: [UInt16]
    var length: Int { units.count }

    init(_ string: String) {
        self.string = string
        units = Array(string.utf16)
    }

    /// The Unicode scalar at UTF-16 index `i` (BMP; surrogate pairs read as
    /// their leading unit - PII text is effectively all BMP).
    func scalar(at i: Int) -> Unicode.Scalar? {
        guard i >= 0, i < units.count else { return nil }
        return Unicode.Scalar(units[i])
    }

    func slice(_ a: Int, _ b: Int) -> String {
        let lo = max(0, min(a, units.count)), hi = max(0, min(b, units.count))
        guard hi > lo else { return "" }
        return String(decoding: units[lo..<hi], as: UTF16.self)
    }

    /// First literal occurrence of `needle` at or after UTF-16 offset `from`.
    func find(_ needle: String, from: Int) -> (start: Int, end: Int)? {
        let n = Array(needle.utf16)
        guard !n.isEmpty, from <= units.count - n.count else { return nil }
        outer: for i in max(0, from)...(units.count - n.count) {
            for j in 0..<n.count where units[i + j] != n[j] { continue outer }
            return (i, i + n.count)
        }
        return nil
    }

    func isWhitespace(at i: Int) -> Bool {
        guard let s = scalar(at: i) else { return false }
        return s.properties.isWhitespace
    }

    func isWordChar(at i: Int) -> Bool {
        guard let s = scalar(at: i) else { return false }
        if s.properties.isAlphabetic || s.properties.numericType != nil { return true }
        switch s.properties.generalCategory {
        case .decimalNumber, .letterNumber, .otherNumber,
             .nonspacingMark, .spacingMark, .enclosingMark:
            return true
        default:
            return false
        }
    }
}


// Test the exact guard-relevant original predicates. The downstream regex/name
// decision is opaque and tested for BOTH booleans, proving independence from it.
func nameLike(_ gap: String, tail: Bool) -> Bool {
    if gap.allSatisfy({ $0.isWhitespace }) { return false }
    if gap.utf16.count > 20 { return false }
    return tail
}
func adjacent(_ t: UTF16Text, _ a: Span, _ b: Span, tail: Bool, fast: Bool) -> Bool {
    let (lo, hi) = a.start <= b.start ? (a, b) : (b, a)
    if hi.start < lo.end { return true }
    if fast && hi.start - lo.end > 20 { return false }
    let gap = t.slice(lo.end, hi.start)
    return (gap.allSatisfy({ $0.isWhitespace }) && gap.utf16.count <= 3) || nameLike(gap, tail: tail)
}
func bridge(_ t: UTF16Text, _ p: Span, _ s: Span, tail: Bool, fast: Bool) -> Bool {
    return s.start >= p.end && (!fast || s.start - p.end <= 20) && nameLike(t.slice(p.end, s.start), tail: tail)
}
var checks = 0
func check(_ text: String, _ a: Span, _ b: Span) {
    let t = UTF16Text(text)
    for tail in [false, true] {
        for pair in [(a,b), (b,a)] {
            let expectedA = adjacent(t, pair.0, pair.1, tail: tail, fast: false)
            let actualA = adjacent(t, pair.0, pair.1, tail: tail, fast: true)
            let expectedB = bridge(t, pair.0, pair.1, tail: tail, fast: false)
            let actualB = bridge(t, pair.0, pair.1, tail: tail, fast: true)
            if expectedA != actualA || expectedB != actualB { fatalError("gap predicate mismatch") }
            checks += 2
        }
    }
}
let pieces = [" ", "\t", "\r\n", "\u{00a0}", "\u{2003}", "A", "a", "\u{0301}", "😀", "𐐀", "Z", "-", "de", "É", "👨‍👩‍👧‍👦", "中"]
for length in [0,1,2,3,4,19,20,21,22,100,2048] {
    for piece in pieces {
        let gap = String(decoding: Array(String(repeating: piece, count: length + 1).utf16).prefix(length), as: UTF16.self)
        let text = "A" + gap + "B"
        let n = text.utf16.count
        check(text, Span(0,1,"GIVEN_NAME"), Span(n-1,n,"SURNAME"))
        check(text, Span(0,n,"GIVEN_NAME"), Span(n-1,n,"SURNAME"))
        check(text, Span(0,n,"GIVEN_NAME"), Span(0,n,"SURNAME"))
    }
}
var random: UInt64 = 678
func next(_ upper: Int) -> Int {
    random = random &* 6364136223846793005 &+ 1442695040888963407
    return Int((random >> 32) % UInt64(upper))
}
for _ in 0..<20000 {
    let text = (0..<next(100)).map { _ in pieces[next(pieces.count)] }.joined()
    let n = text.utf16.count
    let x = next(n+1), y = next(n+1), z = next(n+1), w = next(n+1)
    check(text, Span(min(x,y),max(x,y),"GIVEN_NAME"), Span(min(z,w),max(z,w),"SURNAME"))
}
print("PASS \(checks) Swift predicate equivalence checks; valid UTF16 offsets, Unicode/surrogate cuts, overlap, equal starts, whitespace, exact20 boundary; opaque downstream result exhaustive")
