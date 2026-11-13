//! Repair of an assistant-authored update diff into an exact unified diff.
//!
//! Models write correct hunk bodies but often wrong `@@` counts or line
//! numbers, or blank context lines without the leading space; the exact
//! applier refuses those, so a coding turn loops on `invalid_patch`. Here each
//! hunk's old lines (context and removals) are located verbatim in the base
//! text, and the headers are rebuilt from where they really are. Nothing is
//! guessed: a hunk whose old lines do not occur, occur ambiguously or touch a
//! final line without newline is refused. The repaired diff is what gets
//! applied and stored, so revision history replays exactly
//! (spec `feature.projects`, agentic coding file updates).

/// One hunk body as `(prefix, line)` rows, prefix `b' '`, `b'-'` or `b'+'`.
struct Hunk<'a> {
    stated_old_start: usize,
    rows: Vec<(u8, &'a str)>,
}

/// Rebuild `diff` (whose headers the caller already checked) against
/// `original`, or `None` when it cannot be located unambiguously.
pub(super) fn repair_patch(original: &str, diff: &str) -> Option<String> {
    if diff.contains('\0') || diff.contains('\r') {
        return None;
    }
    let mut rows: Vec<&str> = diff.split('\n').collect();
    if rows.last() == Some(&"") {
        rows.pop();
    }
    let (old_header, new_header) = (rows.first()?, rows.get(1)?);
    let hunks = parse_hunks(&rows[2..])?;
    let source: Vec<&str> = original.split_inclusive('\n').collect();
    let ends_with_newline = original.is_empty() || original.ends_with('\n');
    let line = |index: usize| source[index].strip_suffix('\n').unwrap_or(source[index]);

    let mut out = format!("{old_header}\n{new_header}\n");
    let (mut cursor, mut offset) = (0usize, 0isize);
    for hunk in hunks {
        let old: Vec<&str> = hunk
            .rows
            .iter()
            .filter(|(k, _)| *k != b'+')
            .map(|(_, v)| *v)
            .collect();
        let new_count = hunk.rows.iter().filter(|(k, _)| *k != b'-').count();
        // A pure insertion has no anchor to verify; only exact diffs may add one.
        if old.is_empty() {
            return None;
        }
        let candidates: Vec<usize> = (cursor..=source.len().saturating_sub(old.len()))
            .filter(|&at| at + old.len() <= source.len())
            .filter(|&at| {
                old.iter()
                    .enumerate()
                    .all(|(i, value)| line(at + i) == *value)
            })
            .collect();
        let at = closest(&candidates, hunk.stated_old_start.saturating_sub(1))?;
        if !ends_with_newline && at + old.len() == source.len() {
            return None;
        }
        let new_start = at as isize + 1 + offset;
        out.push_str(&format!(
            "@@ -{},{} +{},{} @@\n",
            at + 1,
            old.len(),
            new_start,
            new_count
        ));
        for (kind, value) in &hunk.rows {
            out.push(char::from(*kind));
            out.push_str(value);
            out.push('\n');
        }
        offset += new_count as isize - old.len() as isize;
        cursor = at + old.len();
    }
    Some(out)
}

/// Split the rows after the file headers into hunks; a bare empty row is a
/// blank context line (a common model formatting slip).
fn parse_hunks<'a>(rows: &[&'a str]) -> Option<Vec<Hunk<'a>>> {
    let mut hunks: Vec<Hunk<'a>> = Vec::new();
    for row in rows {
        if let Some(header) = row.strip_prefix("@@") {
            hunks.push(Hunk {
                stated_old_start: stated_old_start(header),
                rows: Vec::new(),
            });
            continue;
        }
        let hunk = hunks.last_mut()?;
        let entry = match row.as_bytes().first() {
            None => (b' ', ""),
            Some(kind @ (b' ' | b'-' | b'+')) => (*kind, &row[1..]),
            // No-newline markers and stray text need the exact applier.
            _ => return None,
        };
        hunk.rows.push(entry);
    }
    (!hunks.is_empty() && hunks.iter().all(|h| h.rows.iter().any(|(k, _)| *k != b' ')))
        .then_some(hunks)
}

/// The `-N` of a hunk header, 1 when it is missing or unreadable.
fn stated_old_start(header: &str) -> usize {
    header
        .trim_start()
        .strip_prefix('-')
        .and_then(|rest| rest.split([',', ' ']).next())
        .and_then(|n| n.parse().ok())
        .unwrap_or(1)
}

/// The candidate nearest to the stated start; a tie is ambiguous.
fn closest(candidates: &[usize], stated: usize) -> Option<usize> {
    let best = *candidates.iter().min_by_key(|&&at| at.abs_diff(stated))?;
    let distance = best.abs_diff(stated);
    (candidates
        .iter()
        .filter(|&&at| at.abs_diff(stated) == distance)
        .count()
        == 1)
        .then_some(best)
}
