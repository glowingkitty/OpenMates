//! Chat detail rows for test results: headline, terminal step list and non-result content.
use super::*;

fn text_of(rows: &[Row]) -> String {
    rows.iter()
        .map(|row| row.iter().map(|p| p.text.as_str()).collect::<String>())
        .collect::<Vec<_>>()
        .join("\n")
}

#[test]
fn cli_result_shows_headline_command_output_and_cast() {
    let content = serde_json::json!({
        "kind": "cli", "target": "e2b", "run_status": "failed", "passed": 0, "failed": 1, "duration_ms": 1500,
        "steps": [{"name": "add", "status": "failed", "command": "recipes add", "output": "boom"}],
        "evidence": [{"kind": "terminal_cast", "path": "outputs/test-run/terminal.cast", "asset_id": "cast-1"}],
    });
    let text = text_of(&rows(&content, 80).unwrap());
    assert!(text.starts_with("CLI test failed\n0 passed, 1 failed, 0 skipped in 1.5s"));
    assert!(text.contains("$ recipes add"));
    assert!(text.contains("Cast: outputs/test-run/terminal.cast (asset cast-1)"));
}

#[test]
fn other_content_falls_through_to_the_generic_card() {
    assert!(rows(&serde_json::json!({"language": "python"}), 80).is_none());
}
