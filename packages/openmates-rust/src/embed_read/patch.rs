//! spec: sdk.client.thin-platform-boundary
//! Exact replay of legacy artifact version diffs (port of
//! `embedVersionReconstruction.ts` `applyVersionPatch`
//! and `projectFilePatch.ts` `applyProjectFilePatch`). Decryption of stored rows stays
//! with the Worker's embed write session (`reconstructVersions`); this replays text.
use super::EmbedReadError;

fn err<T>(reason: &'static str) -> Result<T, EmbedReadError> {
    Err(EmbedReadError::new(reason))
}

/// Parses `@@ -a[,b] +c[,d] @@[ ...]`; counts default to 1.
fn parse_hunk_header(line: &str) -> Option<[u64; 4]> {
    let rest = line.strip_prefix("@@ -")?;
    let (old, rest) = rest.split_once(" +")?;
    let (new, tail) = rest.split_once(" @@")?;
    if !(tail.is_empty() || tail.starts_with(' ')) {
        return None;
    }
    let pair = |s: &str| -> Option<(u64, u64)> {
        let (a, b) = match s.split_once(',') {
            Some((a, b)) => (a, Some(b)),
            None => (s, None),
        };
        let num = |t: &str| {
            (!t.is_empty() && t.bytes().all(|c| c.is_ascii_digit()))
                .then(|| t.parse::<u64>().ok())
                .flatten()
        };
        Some((
            num(a)?,
            match b {
                Some(b) => num(b)?,
                None => 1,
            },
        ))
    };
    let (os, oc) = pair(old)?;
    let (ns, nc) = pair(new)?;
    Some([os, oc, ns, nc])
}

/// Applies one stored version patch to `content` (split/join LF; file headers optional).
pub fn apply_version_patch(content: &str, patch: &str) -> Result<String, EmbedReadError> {
    if patch.contains("\\ No newline at end of file") {
        let with_headers;
        let diff = if patch.starts_with("@@ ") {
            with_headers = format!("--- version\n+++ version\n{patch}");
            with_headers.as_str()
        } else {
            patch
        };
        return apply_project_file_patch(content, diff);
    }
    let source: Vec<&str> = if content.is_empty() {
        Vec::new()
    } else {
        content.split('\n').collect()
    };
    let mut lines: Vec<&str> = patch.split('\n').collect();
    if lines.last() == Some(&"") {
        lines.pop();
    }
    let mut index = 0;
    if lines.first().is_some_and(|l| l.starts_with("--- "))
        && lines.get(1).is_some_and(|l| l.starts_with("+++ "))
    {
        index = 2;
    }
    let mut output: Vec<&str> = Vec::new();
    let mut source_index = 0usize;
    let mut hunks = 0;
    while index < lines.len() {
        let Some([old_start, old_count, new_start, new_count]) = parse_hunk_header(lines[index])
        else {
            return err("Version patch contains an invalid hunk");
        };
        let start = if old_count == 0 {
            old_start
        } else {
            old_start.wrapping_sub(1)
        };
        let output_start = if new_count == 0 {
            new_start
        } else {
            new_start.wrapping_sub(1)
        };
        if start < source_index as u64 || start > source.len() as u64 {
            return err("Version patch hunks overlap or exceed content");
        }
        let start = start as usize;
        output.extend_from_slice(&source[source_index..start]);
        if output.len() as u64 != output_start {
            return err("Version patch coordinates do not match content");
        }
        source_index = start;
        let (mut removed, mut added) = (0u64, 0u64);
        index += 1;
        while index < lines.len() && !lines[index].starts_with("@@ ") {
            let line = lines[index];
            if line == "\\ No newline at end of file" {
                index += 1;
                continue;
            }
            let prefix = line.as_bytes().first().copied();
            if !matches!(prefix, Some(b' ' | b'-' | b'+')) {
                return err("Version patch has an invalid line");
            }
            if prefix != Some(b'+') {
                if source.get(source_index) != Some(&&line[1..]) {
                    return err("Version patch context does not match local content");
                }
                source_index += 1;
                removed += 1;
            }
            if prefix != Some(b'-') {
                output.push(&line[1..]);
                added += 1;
            }
            index += 1;
        }
        if removed != old_count || added != new_count {
            return err("Version patch line counts do not match its header");
        }
        hunks += 1;
    }
    if hunks == 0 {
        return err("Version patch has no hunks");
    }
    output.extend_from_slice(&source[source_index..]);
    Ok(output.join("\n"))
}

struct Line {
    value: String,
    has_newline: bool,
}

fn split_content_lines(content: &str) -> Vec<Line> {
    let mut lines = Vec::new();
    let mut rest = content;
    while let Some(pos) = rest.find('\n') {
        lines.push(Line {
            value: rest[..pos].to_string(),
            has_newline: true,
        });
        rest = &rest[pos + 1..];
    }
    if !rest.is_empty() {
        lines.push(Line {
            value: rest.to_string(),
            has_newline: false,
        });
    }
    lines
}

fn header_path(row: &str, marker: &str) -> Option<String> {
    let rest = row.strip_prefix(marker)?.strip_prefix(' ')?;
    let path = rest.split('\t').next().unwrap_or("");
    if path.is_empty() {
        return None;
    }
    Some(if path.starts_with("a/") || path.starts_with("b/") {
        path[2..].to_string()
    } else {
        path.to_string()
    })
}

/// Applies a one-file unified diff exactly at its declared positions.
pub fn apply_project_file_patch(original: &str, diff: &str) -> Result<String, EmbedReadError> {
    if diff.is_empty() || diff.contains('\0') || diff.contains('\r') {
        return err("Patch must be a non-empty LF unified diff");
    }
    let mut rows: Vec<&str> = diff.split('\n').collect();
    if rows.last() == Some(&"") {
        rows.pop();
    }
    if rows.len() < 3 {
        return err("Patch is missing file headers or hunks");
    }
    let (Some(old_path), Some(new_path)) =
        (header_path(rows[0], "---"), header_path(rows[1], "+++"))
    else {
        return err("Patch must start with one old and one new file header");
    };
    if old_path == "/dev/null" || new_path == "/dev/null" {
        return err("Update patches cannot create or delete files");
    }
    struct Hunk {
        old_start: u64,
        old_count: u64,
        new_start: u64,
        new_count: u64,
        lines: Vec<(u8, Line)>,
    }
    let mut hunks: Vec<Hunk> = Vec::new();
    let mut row = 2;
    while row < rows.len() {
        let Some([os, oc, ns, nc]) = parse_hunk_header(rows[row]) else {
            return err("Patch contains data outside a valid hunk");
        };
        let mut hunk = Hunk {
            old_start: os,
            old_count: oc,
            new_start: ns,
            new_count: nc,
            lines: Vec::new(),
        };
        row += 1;
        let (mut old_seen, mut new_seen) = (0u64, 0u64);
        while row < rows.len() && !rows[row].starts_with("@@ ") {
            let value = rows[row];
            if value == "\\ No newline at end of file" {
                match hunk.lines.last_mut() {
                    Some((_, line)) if line.has_newline => line.has_newline = false,
                    _ => return err("Misplaced no-newline marker"),
                }
                row += 1;
                continue;
            }
            let kind = match value.as_bytes().first() {
                Some(b' ') => b' ',
                Some(b'-') => b'-',
                Some(b'+') => b'+',
                _ => return err("Every hunk line must have a unified-diff prefix"),
            };
            hunk.lines.push((
                kind,
                Line {
                    value: value[1..].to_string(),
                    has_newline: true,
                },
            ));
            if kind != b'+' {
                old_seen += 1;
            }
            if kind != b'-' {
                new_seen += 1;
            }
            row += 1;
        }
        if old_seen != hunk.old_count || new_seen != hunk.new_count {
            return err("Hunk line counts do not match its header");
        }
        hunks.push(hunk);
    }
    if hunks.is_empty() {
        return err("Patch has no hunks");
    }
    let source = split_content_lines(original);
    let mut output: Vec<Line> = Vec::new();
    let mut source_index = 0usize;
    let mut output_line = 1u64;
    for hunk in hunks {
        let expected_source = if hunk.old_count == 0 {
            hunk.old_start
        } else {
            hunk.old_start.wrapping_sub(1)
        };
        let expected_output = if hunk.new_count == 0 {
            hunk.new_start.saturating_add(1)
        } else {
            hunk.new_start
        };
        if expected_source < source_index as u64 || expected_source > source.len() as u64 {
            return err("Patch hunks overlap or are outside the source");
        }
        while (source_index as u64) < expected_source {
            output.push(Line {
                value: source[source_index].value.clone(),
                has_newline: source[source_index].has_newline,
            });
            source_index += 1;
            output_line += 1;
        }
        if output_line != expected_output {
            return err("Patch new-file coordinates are inconsistent");
        }
        for (kind, line) in hunk.lines {
            if kind != b'+' {
                match source.get(source_index) {
                    Some(actual)
                        if actual.value == line.value && actual.has_newline == line.has_newline => {
                    }
                    _ => return err("Patch context does not match the source exactly"),
                }
                source_index += 1;
            }
            if kind != b'-' {
                output.push(line);
                output_line += 1;
            }
        }
    }
    for line in &source[source_index..] {
        output.push(Line {
            value: line.value.clone(),
            has_newline: line.has_newline,
        });
    }
    if output.iter().rev().skip(1).any(|l| !l.has_newline) {
        return err("No-newline marker is only valid at end of file");
    }
    Ok(output
        .iter()
        .map(|l| {
            if l.has_newline {
                format!("{}\n", l.value)
            } else {
                l.value.clone()
            }
        })
        .collect())
}
