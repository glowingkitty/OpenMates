//! Exact one-file unified-diff applier and the create-file diff, shared by the
//! filesystem host's `update_file` / `create_file`.
//!
//! Mirrors `applyProjectFilePatch` (`ui/src/utils/projectFilePatch.ts`) and
//! `createFileDiff` (`openmates-cli/src/remoteFileWrites.ts`): hunks apply only
//! at their declared positions; context, counts, ordering and final-newline
//! markers must match exactly, so a stale patch never lands on changed text.

/// A rejected patch; the host reports it as `invalid_patch`.
#[derive(Debug, PartialEq, Eq)]
pub(crate) struct PatchError(pub(crate) &'static str);

#[derive(Clone, PartialEq, Eq)]
struct Line {
    value: String,
    newline: bool,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Kind {
    Context,
    Remove,
    Add,
}

struct Hunk {
    old_start: usize,
    old_count: usize,
    new_start: usize,
    new_count: usize,
    lines: Vec<(Kind, Line)>,
}

fn header(row: &str, marker: &str) -> Option<String> {
    let rest = row.strip_prefix(marker)?.strip_prefix(' ')?;
    let path = rest.split('\t').next()?;
    (!path.is_empty()).then(|| path.to_owned())
}

fn normalize_header(value: String) -> String {
    if value == "/dev/null" {
        return value;
    }
    match value.strip_prefix("a/").or_else(|| value.strip_prefix("b/")) {
        Some(rest) => rest.to_owned(),
        None => value,
    }
}

fn coordinate(value: &str) -> Result<usize, PatchError> {
    if value.is_empty() || !value.bytes().all(|b| b.is_ascii_digit()) {
        return Err(PatchError("Invalid hunk coordinate"));
    }
    value
        .parse::<usize>()
        .ok()
        .filter(|v| *v <= (1usize << 53) - 1)
        .ok_or(PatchError("Invalid hunk coordinate"))
}

/// `@@ -a[,b] +c[,d] @@[ text]`.
fn hunk_header(row: &str) -> Option<[Option<&str>; 4]> {
    let rest = row.strip_prefix("@@ -")?;
    let (ranges, tail) = rest.split_once(" @@")?;
    if !(tail.is_empty() || tail.starts_with(' ')) {
        return None;
    }
    let (old, new) = ranges.split_once(" +")?;
    fn split(range: &str) -> Option<(&str, Option<&str>)> {
        let (start, count) = match range.split_once(',') {
            Some((s, c)) => (s, Some(c)),
            None => (range, None),
        };
        fn digits(v: &str) -> bool {
            !v.is_empty() && v.bytes().all(|b| b.is_ascii_digit())
        }
        (digits(start) && count.is_none_or(digits)).then_some((start, count))
    }
    let (a, b) = split(old)?;
    let (c, d) = split(new)?;
    Some([Some(a), b, Some(c), d])
}

fn split_lines(content: &str) -> Vec<Line> {
    let mut lines = Vec::new();
    let mut rest = content;
    while let Some(index) = rest.find('\n') {
        lines.push(Line {
            value: rest[..index].to_owned(),
            newline: true,
        });
        rest = &rest[index + 1..];
    }
    if !rest.is_empty() {
        lines.push(Line {
            value: rest.to_owned(),
            newline: false,
        });
    }
    lines
}

/// Apply `diff` to `original`; header paths must equal `expected_path`.
///
/// # Errors
/// [`PatchError`] with the npm message for any mismatch.
pub(crate) fn apply(original: &str, diff: &str, expected_path: &str) -> Result<String, PatchError> {
    if diff.is_empty() || diff.contains('\0') || diff.contains('\r') {
        return Err(PatchError("Patch must be a non-empty LF unified diff"));
    }
    let mut rows: Vec<&str> = diff.split('\n').collect();
    if rows.last() == Some(&"") {
        rows.pop();
    }
    if rows.len() < 3 {
        return Err(PatchError("Patch is missing file headers or hunks"));
    }
    let (Some(old), Some(new)) = (header(rows[0], "---"), header(rows[1], "+++")) else {
        return Err(PatchError(
            "Patch must start with one old and one new file header",
        ));
    };
    let (old, new) = (normalize_header(old), normalize_header(new));
    if old == "/dev/null" || new == "/dev/null" {
        return Err(PatchError("Update patches cannot create or delete files"));
    }
    if !expected_path.is_empty() && (old != expected_path || new != expected_path) {
        return Err(PatchError(
            "Patch file headers do not match the requested path",
        ));
    }
    let mut hunks = Vec::new();
    let mut row = 2;
    while row < rows.len() {
        let Some([a, b, c, d]) = hunk_header(rows[row]) else {
            return Err(PatchError("Patch contains data outside a valid hunk"));
        };
        let mut hunk = Hunk {
            old_start: coordinate(a.unwrap_or_default())?,
            old_count: b.map(coordinate).transpose()?.unwrap_or(1),
            new_start: coordinate(c.unwrap_or_default())?,
            new_count: d.map(coordinate).transpose()?.unwrap_or(1),
            lines: Vec::new(),
        };
        row += 1;
        let (mut old_seen, mut new_seen) = (0, 0);
        while row < rows.len() && !rows[row].starts_with("@@ ") {
            let value = rows[row];
            if value == "\\ No newline at end of file" {
                match hunk.lines.last_mut() {
                    Some((_, line)) if line.newline => line.newline = false,
                    _ => return Err(PatchError("Misplaced no-newline marker")),
                }
                row += 1;
                continue;
            }
            let kind = match value.as_bytes().first() {
                Some(b' ') => Kind::Context,
                Some(b'-') => Kind::Remove,
                Some(b'+') => Kind::Add,
                _ => {
                    return Err(PatchError(
                        "Every hunk line must have a unified-diff prefix",
                    ));
                }
            };
            hunk.lines.push((
                kind,
                Line {
                    value: value[1..].to_owned(),
                    newline: true,
                },
            ));
            if kind != Kind::Add {
                old_seen += 1;
            }
            if kind != Kind::Remove {
                new_seen += 1;
            }
            row += 1;
        }
        if old_seen != hunk.old_count || new_seen != hunk.new_count {
            return Err(PatchError("Hunk line counts do not match its header"));
        }
        hunks.push(hunk);
    }
    if hunks.is_empty() {
        return Err(PatchError("Patch has no hunks"));
    }
    let source = split_lines(original);
    let mut output: Vec<Line> = Vec::new();
    let (mut index, mut output_line) = (0usize, 1usize);
    for hunk in &hunks {
        let expected_index = if hunk.old_count == 0 {
            hunk.old_start
        } else {
            hunk.old_start.wrapping_sub(1)
        };
        let expected_output = if hunk.new_count == 0 {
            hunk.new_start + 1
        } else {
            hunk.new_start
        };
        if expected_index < index || expected_index > source.len() {
            return Err(PatchError(
                "Patch hunks overlap or are outside the source",
            ));
        }
        while index < expected_index {
            output.push(source[index].clone());
            index += 1;
            output_line += 1;
        }
        if output_line != expected_output {
            return Err(PatchError("Patch new-file coordinates are inconsistent"));
        }
        for (kind, line) in &hunk.lines {
            if *kind != Kind::Add {
                if source.get(index) != Some(line) {
                    return Err(PatchError(
                        "Patch context does not match the source exactly",
                    ));
                }
                index += 1;
            }
            if *kind != Kind::Remove {
                output.push(line.clone());
                output_line += 1;
            }
        }
    }
    output.extend(source[index..].iter().cloned());
    if output.iter().rev().skip(1).any(|line| !line.newline) {
        return Err(PatchError(
            "No-newline marker is only valid at end of file",
        ));
    }
    Ok(output
        .iter()
        .map(|line| {
            if line.newline {
                format!("{}\n", line.value)
            } else {
                line.value.clone()
            }
        })
        .collect())
}

/// npm `createFileDiff`: the `/dev/null` diff for a new file.
pub(crate) fn create_diff(path: &str, content: &str) -> String {
    if content.is_empty() {
        return format!("--- /dev/null\n+++ b/{path}\n");
    }
    let final_newline = content.ends_with('\n');
    let mut lines: Vec<&str> = content.split('\n').collect();
    if final_newline {
        lines.pop();
    }
    let body: String = lines.iter().map(|line| format!("+{line}\n")).collect();
    format!(
        "--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{} @@\n{body}{}",
        lines.len(),
        if final_newline {
            ""
        } else {
            "\\ No newline at end of file\n"
        }
    )
}
