//! Non-overlapping hunks merge, overlapping hunks conflict, nothing is lost.
use super::merge3;

fn ten() -> String {
    (1..=10).map(|n| format!("line {n}\n")).collect()
}

#[test]
fn merges_non_overlapping_hunks() {
    let base = ten();
    let ours = base.replace("line 2\n", "ours 2\n");
    let theirs = base.replace("line 8\n", "theirs 8\n");
    let (merged, conflicted) = merge3(&ours, &base, &theirs);
    assert!(!conflicted);
    assert_eq!(
        merged,
        base.replace("line 2\n", "ours 2\n")
            .replace("line 8\n", "theirs 8\n")
    );
}

#[test]
fn overlapping_hunks_conflict_with_both_versions_kept() {
    let base = ten();
    let (merged, conflicted) = merge3(
        &base.replace("line 5", "ours 5"),
        &base,
        &base.replace("line 5", "theirs 5"),
    );
    assert!(conflicted);
    assert!(merged.contains("<<<<<<< local\nours 5\n=======\ntheirs 5\n>>>>>>> other\n"));
}

#[test]
fn identical_edits_on_both_sides_are_not_a_conflict() {
    let base = ten();
    let both = base.replace("line 5", "same 5");
    assert_eq!(merge3(&both, &base, &both), (both, false));
}

#[test]
fn insertions_and_deletions_in_different_places_merge() {
    let base = ten();
    let ours = format!("top\n{base}");
    let theirs = base.replace("line 9\n", "");
    let (merged, conflicted) = merge3(&ours, &base, &theirs);
    assert!(!conflicted);
    assert!(merged.starts_with("top\nline 1\n") && !merged.contains("line 9"));
}

#[test]
fn unchanged_side_takes_the_other_side() {
    let base = ten();
    let theirs = base.replace("line 3", "new 3");
    assert_eq!(merge3(&base, &base, &theirs), (theirs, false));
}
