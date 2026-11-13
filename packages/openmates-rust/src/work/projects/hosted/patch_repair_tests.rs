//! Assistant update diffs with wrong hunk headers are located by their exact old lines, repaired and stored as exact diffs.
use super::*;

const TEST: &str = "import { test } from '@playwright/test';\n\ntest('adds', async ({ page }) => {\n  await page.goto('/');\n  await expect(page.getByRole('heading', { name: 'Pancakes' })).toBeVisible();\n});\n";
const PATH: &str = "web-app/tests/recipe.spec.js";

fn diff(body: &str) -> String {
    format!("--- a/{PATH}\n+++ b/{PATH}\n{body}")
}

#[test]
fn wrong_hunk_counts_and_start_are_repaired_and_stored_exactly() {
    // Off-by-two start and a count that ignores the blank context line.
    let model = diff(
        "@@ -3,2 +3,2 @@\n   await page.goto('/');\n-  await expect(page.getByRole('heading', { name: 'Pancakes' })).toBeVisible();\n+  await expect(page.getByRole('heading', { name: 'Pancakes', level: 2 })).toBeVisible();\n });\n",
    );
    let expected = TEST.replace("'Pancakes' })", "'Pancakes', level: 2 })");
    assert_eq!(
        apply_exact_patch(TEST, &model, PATH),
        Err(HostedFileError::Refused("invalid_patch"))
    );
    let (next, stored) = apply_update_patch(TEST, &model, PATH).unwrap();
    assert_eq!(next, expected);
    assert!(stored.contains("@@ -4,3 +4,3 @@\n"), "{stored}");
    assert_eq!(apply_exact_patch(TEST, &stored, PATH).unwrap(), expected);
}

#[test]
fn blank_context_line_without_space_is_accepted() {
    let model = diff(
        "@@ -1,3 +1,3 @@\n-import { test } from '@playwright/test';\n+import { test, expect } from '@playwright/test';\n\n test('adds', async ({ page }) => {\n",
    );
    let (next, _) = apply_update_patch(TEST, &model, PATH).unwrap();
    assert!(next.starts_with("import { test, expect } from '@playwright/test';\n\ntest('adds'"));
}

#[test]
fn exact_diffs_are_stored_unchanged() {
    let exact =
        diff("@@ -4,1 +4,1 @@\n-  await page.goto('/');\n+  await page.goto('/recipes');\n");
    let (_, stored) = apply_update_patch(TEST, &exact, PATH).unwrap();
    assert_eq!(stored, exact);
}

#[test]
fn unlocatable_or_ambiguous_hunks_stay_refused() {
    let refused = Err(HostedFileError::Refused("invalid_patch"));
    // Old line not in the file.
    let missing = diff("@@ -1,1 +1,1 @@\n-const nope = 1;\n+const yes = 1;\n");
    assert_eq!(apply_update_patch(TEST, &missing, PATH), refused);
    // The same line twice, stated start equally far from both.
    let twice = "a\nx\nb\nx\nc\n";
    let ambiguous = diff("@@ -3,1 +3,1 @@\n-x\n+y\n");
    assert_eq!(apply_update_patch(twice, &ambiguous, PATH), refused);
    // A pure insertion has no anchor to check.
    let insertion = diff("@@ -9,0 +9,1 @@\n+// added\n");
    assert_eq!(apply_update_patch(TEST, &insertion, PATH), refused);
    // A final line without newline needs the exact marker.
    let unterminated = diff("@@ -2,1 +2,1 @@\n-b\n+c\n");
    assert_eq!(apply_update_patch("a\nb", &unterminated, PATH), refused);
    // Another file's headers are never repaired into this one.
    let other = "--- a/other.js\n+++ b/other.js\n@@ -9,1 +9,1 @@\n-  await page.goto('/');\n+  await page.goto('/x');\n";
    assert_eq!(apply_update_patch(TEST, other, PATH), refused);
}
