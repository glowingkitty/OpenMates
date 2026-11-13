//! Chat detail rows for the `code-test-result` embed (opened from the chat
//! carousel). TUI adapter: decoding and the render model come from
//! `openmates_sdk::test_result_embed`; this only styles the lines. The full
//! printable report is `openmates embeds test-result`.
use super::super::markdown::{self, Row};
use super::super::{ACCENT, MUTED, TEXT};
use openmates_sdk::test_result_embed::{RunStatus, TestResultEmbed};
use ratatui::style::{Color, Style};
use serde_json::Value;

/// Rows for decrypted test result content; `None` when it is not a test result,
/// so the generic card is shown instead of a decode error.
pub(super) fn rows(content: &Value, width: usize) -> Option<Vec<Row>> {
    let embed = TestResultEmbed::decode_json(&content.to_string()).ok()?;
    let view = embed.render_model();
    let status_color = match view.status {
        RunStatus::Passed => Color::Rgb(0x4c, 0xaf, 0x50),
        _ => Color::Rgb(255, 85, 59),
    };
    let mut rows: Vec<Row> = Vec::new();
    let full = view.render_full();
    let mut lines = full.lines().map(str::to_owned);
    if let Some(head) = lines.next() {
        rows.extend(markdown::wrap(
            markdown::styled(head, Style::default().fg(status_color).bold()),
            width,
        ));
    }
    for line in lines {
        let style = if line.starts_with("[FAIL]") || line.starts_with("Error:") {
            Style::default().fg(Color::Rgb(255, 85, 59))
        } else if line.starts_with("Steps") || line.starts_with("Terminal") {
            Style::default().fg(ACCENT).bold()
        } else if line.starts_with(' ') || line.starts_with('$') {
            Style::default().fg(TEXT)
        } else {
            Style::default().fg(MUTED)
        };
        rows.extend(markdown::wrap(markdown::styled(line, style), width));
    }
    Some(rows)
}

#[cfg(test)]
#[path = "test_result_tests.rs"]
mod tests;
