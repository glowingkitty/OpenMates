//! Exact bounded unified-diff reconstruction for encrypted artifact history.
use super::*;
pub(super) fn apply(content: &str, patch: &str) -> Result<String> {
    if content.len() > 16 * 1024 * 1024 || patch.len() > 16 * 1024 * 1024 {
        return Err(Error::Protocol);
    }
    if patch.contains("\\ No newline at end of file") {
        return apply_marker_patch(content, patch);
    }
    // Explicit no-newline metadata changes LF semantics. Preserve it with a
    // separate shape flag instead of treating the marker as an ordinary line.
    let marker = patch.contains("\\ No newline at end of file");
    let mut source: Vec<&str> = if content.is_empty() {
        vec![]
    } else {
        content.split('\n').collect()
    };
    if marker && content.ends_with('\n') {
        source.pop();
    }
    let mut lines: Vec<&str> = patch.split('\n').collect();
    if lines.last() == Some(&"") {
        lines.pop();
    }
    let mut cursor = if lines.first().is_some_and(|s| s.starts_with("--- "))
        && lines.get(1).is_some_and(|s| s.starts_with("+++ "))
    {
        2
    } else {
        0
    };
    let mut source_cursor = 0usize;
    let mut output: Vec<&str> = vec![];
    let mut hunks = 0;
    let mut no_final_newline = false;
    let header = regex::Regex::new(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$")
        .expect("static hunk regex");
    while cursor < lines.len() {
        let captures = header.captures(lines[cursor]).ok_or(Error::Protocol)?;
        let number = |i| {
            captures
                .get(i)
                .map(|m| m.as_str().parse::<usize>().map_err(|_| Error::Protocol))
                .transpose()
        };
        let old_start = number(1)?.ok_or(Error::Protocol)?;
        let old_count = number(2)?.unwrap_or(1);
        let new_start = number(3)?.ok_or(Error::Protocol)?;
        let new_count = number(4)?.unwrap_or(1);
        let start = if old_count == 0 {
            old_start
        } else {
            old_start.checked_sub(1).ok_or(Error::Protocol)?
        };
        let output_start = if new_count == 0 {
            new_start
        } else {
            new_start.checked_sub(1).ok_or(Error::Protocol)?
        };
        if start < source_cursor || start > source.len() {
            return Err(Error::Protocol);
        }
        output.extend_from_slice(&source[source_cursor..start]);
        if output.len() != output_start {
            return Err(Error::Protocol);
        }
        source_cursor = start;
        let mut removed = 0;
        let mut added = 0;
        let mut previous_op = b' ';
        cursor += 1;
        while cursor < lines.len() && !lines[cursor].starts_with("@@ ") {
            let line = lines[cursor];
            if line == "\\ No newline at end of file" {
                if !marker {
                    return Err(Error::Protocol);
                }
                if previous_op != b'-' {
                    no_final_newline = true;
                }
                cursor += 1;
                continue;
            }
            let op = *line.as_bytes().first().ok_or(Error::Protocol)?;
            if !b" -+".contains(&op) {
                return Err(Error::Protocol);
            }
            let body = &line[1..];
            if op != b'+' {
                if source.get(source_cursor) != Some(&body) {
                    return Err(Error::Protocol);
                }
                source_cursor += 1;
                removed += 1;
            }
            if op != b'-' {
                output.push(body);
                added += 1;
            }
            previous_op = op;
            cursor += 1;
        }
        if removed != old_count || added != new_count {
            return Err(Error::Protocol);
        }
        hunks += 1;
    }
    if hunks == 0 {
        return Err(Error::Protocol);
    }
    output.extend_from_slice(&source[source_cursor..]);
    let mut result = output.join("\n");
    if marker && !no_final_newline && !output.is_empty() {
        result.push('\n');
    }
    if result.len() > 16 * 1024 * 1024 {
        return Err(Error::Protocol);
    }
    Ok(result)
}

// Maintained applyVersionPatch delegates marker-containing patches to the strict
// project-file parser. Keep every line's LF bit: a marker is not a global flag.
#[derive(Clone, Copy)]
struct MarkerLine<'a> {
    value: &'a str,
    has_newline: bool,
}
fn apply_marker_patch(content: &str, patch: &str) -> Result<String> {
    const LIMIT: usize = 16 * 1024 * 1024;
    if patch.is_empty() || patch.contains(['\0', '\r']) {
        return Err(Error::Protocol);
    }
    let mut rows: Vec<&str> = patch.split('\n').collect();
    if rows.last() == Some(&"") {
        rows.pop();
    }
    let mut row = if patch.starts_with("@@ ") {
        0
    } else {
        if rows.len() < 3 {
            return Err(Error::Protocol);
        }
        let header = regex::Regex::new(r"^(---|\+\+\+) ([^\t]+)(?:\t[^\n\r\u{2028}\u{2029}]*)?$")
            .expect("static file header");
        for (index, prefix) in [(0, "---"), (1, "+++")] {
            let captures = header.captures(rows[index]).ok_or(Error::Protocol)?;
            if &captures[1] != prefix {
                return Err(Error::Protocol);
            }
            let path = &captures[2];
            let path = path
                .strip_prefix("a/")
                .or_else(|| path.strip_prefix("b/"))
                .unwrap_or(path);
            if path == "/dev/null" {
                return Err(Error::Protocol);
            }
        }
        2
    };
    let source: Vec<MarkerLine<'_>> = content
        .split_inclusive('\n')
        .map(|value| match value.strip_suffix('\n') {
            Some(value) => MarkerLine {
                value,
                has_newline: true,
            },
            None => MarkerLine {
                value,
                has_newline: false,
            },
        })
        .collect();
    let header = regex::Regex::new(
        r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: [^\n\r\u{2028}\u{2029}]*)?$",
    )
    .expect("static hunk header");
    let mut output: Vec<MarkerLine<'_>> = Vec::new();
    let mut source_index = 0usize;
    let mut hunks = 0;
    while row < rows.len() {
        let captures = header.captures(rows[row]).ok_or(Error::Protocol)?;
        let coordinate = |index: usize, default: Option<usize>| -> Result<usize> {
            let value = match captures.get(index) {
                Some(value) => value.as_str().parse::<u64>().map_err(|_| Error::Protocol)?,
                None => return default.ok_or(Error::Protocol),
            };
            if value > 9_007_199_254_740_991 {
                return Err(Error::Protocol);
            }
            usize::try_from(value).map_err(|_| Error::Protocol)
        };
        let old_start = coordinate(1, None)?;
        let old_count = coordinate(2, Some(1))?;
        let new_start = coordinate(3, None)?;
        let new_count = coordinate(4, Some(1))?;
        row += 1;
        let mut lines: Vec<(u8, MarkerLine<'_>)> = Vec::new();
        let (mut old_seen, mut new_seen) = (0usize, 0usize);
        while row < rows.len() && !rows[row].starts_with("@@ ") {
            let value = rows[row];
            if value == "\\ No newline at end of file" {
                let (_, previous) = lines.last_mut().ok_or(Error::Protocol)?;
                if !previous.has_newline {
                    return Err(Error::Protocol);
                }
                previous.has_newline = false;
            } else {
                let kind = *value.as_bytes().first().ok_or(Error::Protocol)?;
                if !b" -+".contains(&kind) {
                    return Err(Error::Protocol);
                }
                lines.push((
                    kind,
                    MarkerLine {
                        value: &value[1..],
                        has_newline: true,
                    },
                ));
                if kind != b'+' {
                    old_seen += 1;
                }
                if kind != b'-' {
                    new_seen += 1;
                }
            }
            row += 1;
        }
        if old_seen != old_count || new_seen != new_count {
            return Err(Error::Protocol);
        }
        let expected_source = if old_count == 0 {
            old_start
        } else {
            old_start.checked_sub(1).ok_or(Error::Protocol)?
        };
        let expected_output = if new_count == 0 {
            new_start
        } else {
            new_start.checked_sub(1).ok_or(Error::Protocol)?
        };
        if expected_source < source_index || expected_source > source.len() {
            return Err(Error::Protocol);
        }
        output.extend_from_slice(&source[source_index..expected_source]);
        source_index = expected_source;
        if output.len() != expected_output {
            return Err(Error::Protocol);
        }
        for (kind, line) in lines {
            if kind != b'+' {
                let actual = source.get(source_index).ok_or(Error::Protocol)?;
                if actual.value != line.value || actual.has_newline != line.has_newline {
                    return Err(Error::Protocol);
                }
                source_index += 1;
            }
            if kind != b'-' {
                output.push(line);
            }
        }
        hunks += 1;
    }
    if hunks == 0 {
        return Err(Error::Protocol);
    }
    output.extend_from_slice(&source[source_index..]);
    let mut result = String::new();
    for (index, line) in output.iter().enumerate() {
        if index + 1 < output.len() && !line.has_newline {
            return Err(Error::Protocol);
        }
        let size = result
            .len()
            .checked_add(line.value.len())
            .and_then(|n| n.checked_add(usize::from(line.has_newline)))
            .ok_or(Error::Protocol)?;
        if size > LIMIT {
            return Err(Error::Protocol);
        }
        result.push_str(line.value);
        if line.has_newline {
            result.push('\n');
        }
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn legacy_exact_context_and_lf() {
        assert_eq!(
            apply("a\nb\n", "--- v1\n+++ v2\n@@ -1,3 +1,3 @@\n a\n-b\n+c\n ").unwrap(),
            "a\nc\n"
        );
        assert!(apply("wrong", "@@ -1 +1 @@\n-a\n+b").is_err());
    }
    #[test]
    fn newline_markers() {
        assert_eq!(
            apply(
                "a\n",
                "--- a\n+++ b\n@@ -1 +1 @@\n-a\n+b\n\\ No newline at end of file\n"
            )
            .unwrap(),
            "b"
        );
        assert_eq!(
            apply("a", "@@ -1 +1 @@\n-a\n\\ No newline at end of file\n+b\n").unwrap(),
            "b\n"
        );
    }
    #[test]
    fn marker_source_lf_and_destination_eof_are_exact() {
        let patch = "@@ -1 +1 @@\n-a\n\\ No newline at end of file\n+b\n";
        assert!(matches!(apply("a\n", patch), Err(Error::Protocol)));
        assert_eq!(apply("a", patch).unwrap(), "b\n");
        assert!(
            apply(
                "a\n",
                "@@ -1 +1,2 @@\n-a\n+b\n\\ No newline at end of file\n+c\n"
            )
            .is_err()
        );
        assert!(apply("a\n", "@@ -1 +1 @@\n\\ No newline at end of file\n-a\n+b\n").is_err());
        assert!(
            apply(
                "a\n",
                "@@ -1 +1 @@\n-a\n+b\n\\ No newline at end of file\n\\ No newline at end of file\n"
            )
            .is_err()
        );
    }
    #[test]
    fn marker_comments_and_timestamps_match_javascript_line_terminators() {
        for separator in ['\u{2028}', '\u{2029}', '\r'] {
            for suffix in ["", "tail"] {
                let comment = format!(
                    "@@ -1 +1 @@ x{separator}{suffix}\n-a\n+b\n\\ No newline at end of file\n"
                );
                let timestamp = format!(
                    "--- version\tx{separator}{suffix}\n+++ version\n@@ -1 +1 @@\n-a\n+b\n\\ No newline at end of file\n"
                );
                assert!(matches!(apply("a\n", &comment), Err(Error::Protocol)));
                assert!(matches!(apply("a\n", &timestamp), Err(Error::Protocol)));
            }
        }
    }
    #[test]
    fn refuses_overlaps_and_counts() {
        assert!(apply("a\nb", "@@ -1,2 +1 @@\n-a\n+b").is_err());
        assert!(apply("a", "garbage").is_err());
    }
}
