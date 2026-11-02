//! Grapheme-aware native editor. Secret fields use the same zeroizing storage.
use crossterm::event::{KeyCode, KeyEvent, KeyModifiers};
use unicode_segmentation::UnicodeSegmentation;
use unicode_width::UnicodeWidthStr;
use zeroize::{Zeroize, Zeroizing};

#[derive(Default)]
pub(super) struct Editor {
    pub text: Zeroizing<String>,
    pub cursor: usize,
    preferred_column: Option<usize>,
}
impl Editor {
    pub fn from(text: &str) -> Self {
        Self {
            text: Zeroizing::new(text.to_owned()),
            cursor: text.len(),
            preferred_column: None,
        }
    }
    pub fn clear(&mut self) {
        self.text.zeroize();
        self.text.clear();
        self.cursor = 0;
        self.preferred_column = None;
    }
    pub fn take(&mut self) -> Zeroizing<String> {
        self.cursor = 0;
        self.preferred_column = None;
        std::mem::replace(&mut self.text, Zeroizing::new(String::new()))
    }
    pub fn insert(&mut self, value: &str) {
        // Never allow pasted terminal control sequences to become terminal instructions.
        let mut clean = Zeroizing::new(String::new());
        let mut chars = value.chars().take(262144).peekable();
        while let Some(c) = chars.next() {
            if c == '\r' {
                clean.push('\n');
                if chars.peek() == Some(&'\n') {
                    chars.next();
                }
            } else if !c.is_control() || c == '\n' || c == '\t' {
                clean.push(c);
            }
        }
        if self.text.len() + clean.len() > 1024 * 1024 {
            return;
        }
        self.text.insert_str(self.cursor, &clean);
        self.cursor += clean.len();
        self.snap_forward();
        self.preferred_column = None;
    }
    fn snap_forward(&mut self) {
        if self.cursor < self.text.len() {
            self.cursor = self
                .text
                .grapheme_indices(true)
                .find(|(offset, _)| *offset >= self.cursor)
                .map(|(offset, _)| offset)
                .unwrap_or(self.text.len());
        }
    }
    fn prev(&self) -> usize {
        self.text[..self.cursor]
            .grapheme_indices(true)
            .next_back()
            .map_or(0, |(i, _)| i)
    }
    fn next(&self) -> usize {
        self.text[self.cursor..]
            .graphemes(true)
            .next()
            .map_or(self.cursor, |g| self.cursor + g.len())
    }
    pub fn key(&mut self, key: KeyEvent) {
        let ctrl = key.modifiers.contains(KeyModifiers::CONTROL);
        match key.code {
            KeyCode::Left => {
                self.cursor = self.prev();
                self.preferred_column = None;
            }
            KeyCode::Right => {
                self.cursor = self.next();
                self.preferred_column = None;
            }
            KeyCode::Home => {
                self.cursor = if ctrl {
                    0
                } else {
                    self.text[..self.cursor].rfind('\n').map_or(0, |i| i + 1)
                };
                self.preferred_column = None;
            }
            KeyCode::End => {
                self.cursor = if ctrl {
                    self.text.len()
                } else {
                    self.text[self.cursor..]
                        .find('\n')
                        .map_or(self.text.len(), |i| self.cursor + i)
                };
                self.preferred_column = None;
            }
            KeyCode::Up | KeyCode::Down => self.vertical(key.code == KeyCode::Down),
            KeyCode::Backspace => {
                let p = self.prev();
                self.text.replace_range(p..self.cursor, "");
                self.cursor = p;
                self.snap_forward();
                self.preferred_column = None;
            }
            KeyCode::Delete => {
                let n = self.next();
                self.text.replace_range(self.cursor..n, "");
                self.snap_forward();
                self.preferred_column = None;
            }
            KeyCode::Char('u') if ctrl => self.clear(),
            KeyCode::Char(c)
                if !key
                    .modifiers
                    .intersects(KeyModifiers::CONTROL | KeyModifiers::ALT) =>
            {
                self.insert(&c.to_string())
            }
            _ => {}
        }
    }
    fn vertical(&mut self, down: bool) {
        let start = self.text[..self.cursor].rfind('\n').map_or(0, |i| i + 1);
        let column = self
            .preferred_column
            .unwrap_or_else(|| self.text[start..self.cursor].width());
        let target = if down {
            let Some(end) = self.text[self.cursor..]
                .find('\n')
                .map(|i| self.cursor + i + 1)
            else {
                return;
            };
            end
        } else {
            if start == 0 {
                return;
            }
            self.text[..start - 1].rfind('\n').map_or(0, |i| i + 1)
        };
        let line = self.text[target..].split('\n').next().unwrap_or("");
        let mut used = 0;
        self.cursor = target;
        for g in line.graphemes(true) {
            if used + g.width() > column {
                break;
            }
            used += g.width();
            self.cursor += g.len();
        }
        self.preferred_column = Some(column);
    }
    /// The actual wrapped cell rows and cursor position, shared by painting and hit testing.
    pub fn display(&self, width: usize, masked: bool) -> (Vec<String>, (usize, usize)) {
        let width = width.max(1);
        let mut rows = vec![String::new()];
        let mut col = 0;
        let mut cursor = (0, 0);
        for (offset, g) in self.text.grapheme_indices(true) {
            if offset == self.cursor {
                cursor = (col, rows.len() - 1);
            }
            if g == "\n" {
                rows.push(String::new());
                col = 0;
                continue;
            }
            let value = if masked {
                "•"
            } else if g == "\t" {
                "    "
            } else {
                g
            };
            let cells = value.width();
            if col + cells > width {
                rows.push(String::new());
                col = 0;
            }
            if offset == self.cursor {
                cursor = (col, rows.len() - 1);
            }
            rows.last_mut().unwrap().push_str(value);
            col += cells;
            if col >= width {
                rows.push(String::new());
                col = 0;
            }
        }
        if self.cursor == self.text.len() {
            cursor = (col, rows.len() - 1);
        }
        (rows, cursor)
    }
    pub fn click(&mut self, width: usize, x: usize, y: usize) {
        let mut row = 0;
        let mut col = 0;
        for (offset, g) in self.text.grapheme_indices(true) {
            if row == y && col >= x {
                self.cursor = offset;
                return;
            }
            if g == "\n" {
                if row == y {
                    self.cursor = offset;
                    return;
                }
                row += 1;
                col = 0;
                continue;
            }
            let cells = if g == "\t" { 4 } else { g.width() };
            if col + cells > width.max(1) {
                row += 1;
                col = 0;
            }
            if row == y && col + cells > x {
                self.cursor = offset;
                return;
            }
            col += cells;
            if col >= width.max(1) {
                row += 1;
                col = 0;
            }
        }
        self.cursor = self.text.len();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn edits_complete_graphemes_and_preserves_middle_insert() {
        let mut e = Editor::from("A👩‍💻e\u{301}界");
        e.key(KeyEvent::new(KeyCode::Left, KeyModifiers::NONE));
        e.key(KeyEvent::new(KeyCode::Backspace, KeyModifiers::NONE));
        assert_eq!(&*e.text, "A👩‍💻界");
        e.insert("x");
        assert_eq!(&*e.text, "A👩‍💻x界");
        e.key(KeyEvent::new(KeyCode::Home, KeyModifiers::NONE));
        e.key(KeyEvent::new(KeyCode::Delete, KeyModifiers::NONE));
        assert_eq!(&*e.text, "👩‍💻x界");
    }
    #[test]
    fn multiline_paste_cursor_and_mask() {
        let mut e = Editor::default();
        e.insert("秘密\r\nabc");
        let (rows, cursor) = e.display(4, true);
        assert_eq!(rows, ["••", "•••"]);
        assert_eq!(cursor, (3, 1));
        e.key(KeyEvent::new(KeyCode::Up, KeyModifiers::NONE));
        assert_eq!(e.cursor, 3);
        e.clear();
        assert!(e.text.is_empty());
    }
    #[test]
    fn insertion_that_joins_clusters_keeps_cursor_on_grapheme_boundary() {
        let mut e = Editor::from("👩💻");
        e.key(KeyEvent::new(KeyCode::Left, KeyModifiers::NONE));
        e.insert("\u{200d}");
        assert_eq!(e.text.as_str(), "👩‍💻");
        assert_eq!(e.cursor, e.text.len());
        e.key(KeyEvent::new(KeyCode::Backspace, KeyModifiers::NONE));
        assert!(e.text.is_empty());
    }
}
