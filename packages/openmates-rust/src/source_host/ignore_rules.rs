//! Gitignore-pattern matcher with the semantics of the npm `ignore` package the
//! TS host uses (`createProjectPathPolicy`): last matching rule wins, `!`
//! negation, anchoring when a pattern contains `/`, `**` segments, dir-only
//! trailing `/`, and parent-directory checks so an ignored directory can never be
//! re-included by a negation on one of its children.
//!
//! Candidates are POSIX paths relative to the matcher base; directories carry a
//! trailing `/` (npm `asIgnoreCandidate`).

use super::{HostError, HostResult};
use regex::{Regex, RegexBuilder};

/// One compiled pattern line.
struct Rule {
    negative: bool,
    regex: Regex,
}

/// The npm `ignore().test()` outcome.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub(crate) struct Verdict {
    pub(crate) ignored: bool,
    pub(crate) unignored: bool,
}

/// An ordered rule set from one or more ignore sources.
pub(crate) struct Matcher {
    rules: Vec<Rule>,
}

impl Matcher {
    /// Compile pattern lines. Blank lines, comments and lines ending in an
    /// unescaped backslash are skipped like npm `ignore`.
    ///
    /// # Errors
    /// `invalid_path_policy` when a pattern cannot be compiled.
    pub(crate) fn new<'a>(
        lines: impl IntoIterator<Item = &'a str>,
        ignorecase: bool,
    ) -> HostResult<Self> {
        let mut rules = Vec::new();
        for line in lines {
            if let Some(rule) = compile(line, ignorecase)? {
                rules.push(rule);
            }
        }
        Ok(Self { rules })
    }

    fn test_one(&self, candidate: &str) -> Verdict {
        let mut verdict = Verdict::default();
        for rule in &self.rules {
            // npm `_testOne` with checkUnignored: skip rules that cannot change
            // the current state, otherwise the last match decides.
            if verdict.unignored == rule.negative && verdict.ignored != verdict.unignored {
                continue;
            }
            if rule.regex.is_match(candidate) {
                verdict.ignored = !rule.negative;
                verdict.unignored = rule.negative;
            }
        }
        verdict
    }

    /// npm `test(path)`: every parent directory is checked first; an ignored
    /// parent decides for all of its descendants.
    pub(crate) fn test(&self, candidate: &str) -> Verdict {
        if self.rules.is_empty() || candidate.is_empty() {
            return Verdict::default();
        }
        let trimmed = candidate.strip_suffix('/').unwrap_or(candidate);
        let mut offset = 0;
        while let Some(index) = trimmed[offset..].find('/') {
            let end = offset + index;
            let parent = &candidate[..=end];
            let verdict = self.test_one(parent);
            if verdict.ignored {
                return verdict;
            }
            offset = end + 1;
        }
        self.test_one(candidate)
    }

    /// npm `ignores(path)`.
    pub(crate) fn ignores(&self, candidate: &str) -> bool {
        self.test(candidate).ignored
    }
}

/// npm `asIgnoreCandidate`: `.` is the empty root; directories end with `/`.
pub(crate) fn candidate(path: &str, is_directory: bool) -> String {
    let normalized = if path == "." { "" } else { path };
    if is_directory && !normalized.is_empty() && !normalized.ends_with('/') {
        format!("{normalized}/")
    } else {
        normalized.to_owned()
    }
}

fn trim_trailing_spaces(line: &str) -> &str {
    let bytes = line.as_bytes();
    let mut end = bytes.len();
    while end > 0 && bytes[end - 1] == b' ' {
        // `\ ` keeps one literal trailing space.
        if end >= 2 && bytes[end - 2] == b'\\' {
            break;
        }
        end -= 1;
    }
    &line[..end]
}

fn compile(raw: &str, ignorecase: bool) -> HostResult<Option<Rule>> {
    let line = raw.strip_suffix('\r').unwrap_or(raw);
    if line.trim().is_empty() || line.starts_with('#') {
        return Ok(None);
    }
    let line = trim_trailing_spaces(line);
    // npm REGEX_INVALID_TRAILING_BACKSLASH: an odd number of trailing backslashes.
    let trailing = line.bytes().rev().take_while(|b| *b == b'\\').count();
    if trailing % 2 == 1 {
        return Ok(None);
    }
    let (negative, body) = match line.strip_prefix('!') {
        Some(rest) => (true, rest),
        None => (false, line),
    };
    let body = if body.starts_with("\\!") || body.starts_with("\\#") {
        &body[1..]
    } else {
        body
    };
    let Some(pattern) = translate(body) else {
        return Ok(None);
    };
    let regex = RegexBuilder::new(&pattern)
        .case_insensitive(ignorecase)
        .build()
        .map_err(|_| HostError::new("invalid_path_policy", "Ignore pattern is invalid"))?;
    Ok(Some(Rule { negative, regex }))
}

/// Translate one gitignore pattern to an anchored regex over candidates.
fn translate(pattern: &str) -> Option<String> {
    let mut value = pattern;
    let dir_only = value.len() > 1 && value.ends_with('/');
    if dir_only {
        value = &value[..value.len() - 1];
    }
    let anchored = value.contains('/');
    let value = value.strip_prefix('/').unwrap_or(value);
    if value.is_empty() {
        return None;
    }
    let chars: Vec<char> = value.chars().collect();
    let mut body = String::new();
    let mut i = 0;
    if value.starts_with("**/") {
        body.push_str("(?:.*/)?");
        i = 3;
    }
    while i < chars.len() {
        let rest = &chars[i..];
        if rest.starts_with(&['/', '*', '*', '/']) {
            body.push_str("/(?:.*/)?");
            i += 4;
        } else if rest == ['/', '*', '*'] {
            // `dir/**` matches everything inside `dir`, never `dir` itself.
            body.push_str("/.+");
            i += 3;
        } else if rest.starts_with(&['*', '*']) {
            body.push_str(".*");
            i += 2;
        } else if rest[0] == '*' {
            body.push_str("[^/]*");
            i += 1;
        } else if rest[0] == '?' {
            body.push_str("[^/]");
            i += 1;
        } else if rest[0] == '\\' {
            if let Some(next) = rest.get(1) {
                body.push_str(&regex::escape(&next.to_string()));
            }
            i += 2;
        } else if rest[0] == '[' {
            match class(rest) {
                Some((class, used)) => {
                    body.push_str(&class);
                    i += used;
                }
                None => {
                    body.push_str("\\[");
                    i += 1;
                }
            }
        } else {
            body.push_str(&regex::escape(&rest[0].to_string()));
            i += 1;
        }
    }
    let prefix = if anchored { "^" } else { "^(?:.*/)?" };
    let suffix = if dir_only { "/$" } else { "/?$" };
    Some(format!("{prefix}{body}{suffix}"))
}

/// A `[...]` bracket expression; `!` or `^` first negates. Characters that are
/// special inside Rust regex classes are escaped.
fn class(chars: &[char]) -> Option<(String, usize)> {
    let mut out = String::from("[");
    let mut i = 1;
    if matches!(chars.get(1), Some('!' | '^')) {
        out.push('^');
        i += 1;
    }
    let start = i;
    while i < chars.len() {
        let c = chars[i];
        if c == ']' && i > start {
            out.push(']');
            return Some((out, i + 1));
        }
        match c {
            '\\' => {
                let next = chars.get(i + 1)?;
                // Escaped alphanumerics are literals, not Rust class escapes.
                if !next.is_alphanumeric() {
                    out.push('\\');
                }
                out.push(*next);
                i += 2;
                continue;
            }
            '[' | ']' | '&' | '~' | '^' => {
                out.push('\\');
                out.push(c);
            }
            _ => out.push(c),
        }
        i += 1;
    }
    None
}
