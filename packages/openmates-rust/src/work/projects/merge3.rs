//! Pure three-way line merge for hosted Project files (shared client core).
//! Used when a sandbox write-back meets a newer head: base = the file version the
//! sandbox checked out, ours = the version on the sandbox disk, theirs = the head.
//! Non-overlapping hunks merge; overlapping hunks yield conflict markers and the
//! caller must keep both versions (never overwrite). No `git` binary needed.
//! Spec: `live-collab.assistant.project-code-merge`, `projects.sandbox.write-back`.

/// One changed region of a side relative to the base, in base line indices.
#[derive(Clone, Debug, PartialEq)]
struct Hunk {
    start: usize,
    end: usize,
    lines: Vec<String>,
}

/// LCS table cell cap; larger inputs degrade to one whole-range hunk (more
/// conflicts, never a wrong merge).
const MAX_DIFF_CELLS: usize = 16_000_000;

fn split(text: &str) -> Vec<String> {
    text.split_inclusive('\n').map(str::to_owned).collect()
}

/// Hunks turning `base` into `side`.
fn diff(base: &[String], side: &[String]) -> Vec<Hunk> {
    let prefix = base.iter().zip(side).take_while(|(a, b)| a == b).count();
    let max_suffix = base.len().min(side.len()) - prefix;
    let suffix = base[prefix..]
        .iter()
        .rev()
        .zip(side[prefix..].iter().rev())
        .take(max_suffix)
        .take_while(|(a, b)| a == b)
        .count();
    let b = &base[prefix..base.len() - suffix];
    let s = &side[prefix..side.len() - suffix];
    if b.is_empty() && s.is_empty() {
        return Vec::new();
    }
    let whole = || {
        vec![Hunk {
            start: prefix,
            end: prefix + b.len(),
            lines: s.to_vec(),
        }]
    };
    if (b.len() + 1).saturating_mul(s.len() + 1) > MAX_DIFF_CELLS {
        return whole();
    }
    let w = s.len() + 1;
    let mut table = vec![0u32; (b.len() + 1) * w];
    for i in (0..b.len()).rev() {
        for j in (0..s.len()).rev() {
            table[i * w + j] = if b[i] == s[j] {
                table[(i + 1) * w + j + 1] + 1
            } else {
                table[(i + 1) * w + j].max(table[i * w + j + 1])
            };
        }
    }
    let mut hunks: Vec<Hunk> = Vec::new();
    let (mut i, mut j) = (0, 0);
    let mut open: Option<Hunk> = None;
    while i < b.len() || j < s.len() {
        if i < b.len() && j < s.len() && b[i] == s[j] {
            hunks.extend(open.take());
            i += 1;
            j += 1;
            continue;
        }
        let hunk = open.get_or_insert(Hunk {
            start: prefix + i,
            end: prefix + i,
            lines: Vec::new(),
        });
        if j < s.len() && (i == b.len() || table[i * w + j + 1] >= table[(i + 1) * w + j]) {
            hunk.lines.push(s[j].clone());
            j += 1;
        } else {
            i += 1;
            hunk.end = prefix + i;
        }
    }
    hunks.extend(open);
    hunks
}

fn overlaps(a: &Hunk, b: &Hunk) -> bool {
    (a.start < b.end && b.start < a.end)
        || (a.start == a.end && b.start == b.end && a.start == b.start)
}

/// The base range `start..end` as one side sees it after its hunks apply.
fn side_text(base: &[String], hunks: &[Hunk], start: usize, end: usize) -> Vec<String> {
    let mut out = Vec::new();
    let mut pos = start;
    for h in hunks {
        out.extend_from_slice(&base[pos..h.start]);
        out.extend(h.lines.iter().cloned());
        pos = h.end;
    }
    out.extend_from_slice(&base[pos..end]);
    out
}

/// Merges `ours` and `theirs`, both derived from `base`.
/// Returns the merged text and whether overlapping edits remain as
/// `<<<<<<< local` / `=======` / `>>>>>>> other` conflict blocks.
pub(crate) fn merge3(ours: &str, base: &str, theirs: &str) -> (String, bool) {
    let (b, o, t) = (split(base), split(ours), split(theirs));
    let (oh, th) = (diff(&b, &o), diff(&b, &t));
    let (mut i, mut j, mut pos) = (0, 0, 0);
    let mut out: Vec<String> = Vec::new();
    let mut conflicted = false;
    while i < oh.len() || j < th.len() {
        let take_ours = j >= th.len() || (i < oh.len() && oh[i].start <= th[j].start);
        let (own, other, own_i, other_i) = if take_ours {
            (&oh, &th, i, j)
        } else {
            (&th, &oh, j, i)
        };
        let first = &own[own_i];
        if other_i >= other.len() || !overlaps(first, &other[other_i]) {
            out.extend_from_slice(&b[pos..first.start]);
            out.extend(first.lines.iter().cloned());
            pos = first.end;
            if take_ours {
                i += 1
            } else {
                j += 1
            }
            continue;
        }
        // Grow the cluster until no further hunk of either side touches it.
        // Both first hunks overlap, so both belong to the cluster.
        let (mut ci, mut cj) = (i + 1, j + 1);
        let start = first.start.min(other[other_i].start);
        let mut end = first.end.max(other[other_i].end);
        loop {
            let mut grew = false;
            while ci < oh.len() && oh[ci].start < end {
                end = end.max(oh[ci].end);
                ci += 1;
                grew = true;
            }
            while cj < th.len() && th[cj].start < end {
                end = end.max(th[cj].end);
                cj += 1;
                grew = true;
            }
            if !grew {
                break;
            }
        }
        let ours_text = side_text(&b, &oh[i..ci], start, end);
        let theirs_text = side_text(&b, &th[j..cj], start, end);
        out.extend_from_slice(&b[pos..start]);
        if ours_text == theirs_text {
            out.extend(ours_text);
        } else {
            conflicted = true;
            out.push("<<<<<<< local\n".into());
            out.extend(terminated(ours_text));
            out.push("=======\n".into());
            out.extend(terminated(theirs_text));
            out.push(">>>>>>> other\n".into());
        }
        pos = end;
        i = ci;
        j = cj;
    }
    out.extend_from_slice(&b[pos..]);
    (out.concat(), conflicted)
}

/// Marker lines need a line break before them.
fn terminated(mut lines: Vec<String>) -> Vec<String> {
    if let Some(last) = lines.last_mut()
        && !last.ends_with('\n')
    {
        last.push('\n');
    }
    lines
}

#[cfg(test)]
#[path = "merge3_tests.rs"]
mod merge3_tests;
