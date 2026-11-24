//! Formula references of the sheet adapter. A formula is typed and shown in A1 notation
//! (`=B2*C2`, rows count data rows, the first below the header is 1) but stored with stable
//! row and column ids, so inserting or deleting rows and columns never rewrites it. A stored
//! reference is `⟦{$?}{colId}:{$?}{rowId}⟧`; one whose row or column no longer exists
//! renders `#REF!`.

const OPEN: char = '⟦';
const CLOSE: char = '⟧';

/// Column index (0-based) to letters: 0 -> A, 26 -> AA.
pub(crate) fn column_letters(mut index: usize) -> String {
    let mut out = Vec::new();
    loop {
        out.push(b'A' + (index % 26) as u8);
        if index < 26 {
            break;
        }
        index = index / 26 - 1;
    }
    out.reverse();
    String::from_utf8(out).unwrap_or_default()
}

fn letters_to_index(letters: &str) -> usize {
    letters.bytes().fold(0usize, |acc, b| {
        acc * 26 + usize::from(b.to_ascii_uppercase() - b'A' + 1)
    }) - 1
}

fn is_word(c: char) -> bool {
    c.is_ascii_alphanumeric() || c == '_' || c == '.'
}

/// A1 formula text to the stored form. A reference outside the current grid becomes `#REF!`.
pub(crate) fn to_stored(formula: &str, rows: &[String], cols: &[String]) -> String {
    let chars: Vec<char> = formula.chars().collect();
    let mut out = String::new();
    let mut i = 0;
    let mut in_string = false;
    while i < chars.len() {
        let c = chars[i];
        if c == '"' {
            in_string = !in_string;
        }
        let boundary = i == 0 || !is_word(chars[i - 1]);
        if !in_string && boundary && (c == '$' || c.is_ascii_alphabetic()) {
            if let Some((len, text)) = reference(&chars[i..], rows, cols) {
                out.push_str(&text);
                i += len;
                continue;
            }
        }
        out.push(c);
        i += 1;
    }
    out
}

fn reference(chars: &[char], rows: &[String], cols: &[String]) -> Option<(usize, String)> {
    let mut i = 0;
    let col_abs = chars.get(i) == Some(&'$');
    i += usize::from(col_abs);
    let letters_start = i;
    while i < chars.len() && chars[i].is_ascii_alphabetic() {
        i += 1;
    }
    let letters: String = chars[letters_start..i].iter().collect();
    if letters.is_empty() || letters.len() > 3 {
        return None;
    }
    let row_abs = chars.get(i) == Some(&'$');
    i += usize::from(row_abs);
    let digits_start = i;
    while i < chars.len() && chars[i].is_ascii_digit() {
        i += 1;
    }
    if digits_start == i || chars.get(i).is_some_and(|c| is_word(*c) || *c == '(') {
        return None;
    }
    let row: usize = chars[digits_start..i]
        .iter()
        .collect::<String>()
        .parse()
        .ok()?;
    let col = letters_to_index(&letters);
    let text = match (cols.get(col), row.checked_sub(1).and_then(|r| rows.get(r))) {
        (Some(col_id), Some(row_id)) => format!(
            "{OPEN}{}{col_id}:{}{row_id}{CLOSE}",
            if col_abs { "$" } else { "" },
            if row_abs { "$" } else { "" }
        ),
        _ => "#REF!".to_string(),
    };
    Some((i, text))
}

/// Stored formula to A1 text for the current grid.
pub(crate) fn to_a1(stored: &str, rows: &[String], cols: &[String]) -> String {
    let mut out = String::new();
    let mut rest = stored;
    while let Some(start) = rest.find(OPEN) {
        out.push_str(&rest[..start]);
        let after = &rest[start + OPEN.len_utf8()..];
        let Some(end) = after.find(CLOSE) else {
            out.push_str("#REF!");
            return out;
        };
        out.push_str(&render_reference(&after[..end], rows, cols));
        rest = &after[end + CLOSE.len_utf8()..];
    }
    out.push_str(rest);
    out
}

fn render_reference(body: &str, rows: &[String], cols: &[String]) -> String {
    let Some((col, row)) = body.split_once(':') else {
        return "#REF!".to_string();
    };
    let (col_abs, col_id) = col.strip_prefix('$').map_or((false, col), |c| (true, c));
    let (row_abs, row_id) = row.strip_prefix('$').map_or((false, row), |r| (true, r));
    match (
        cols.iter().position(|c| c == col_id),
        rows.iter().position(|r| r == row_id),
    ) {
        (Some(c), Some(r)) => format!(
            "{}{}{}{}",
            if col_abs { "$" } else { "" },
            column_letters(c),
            if row_abs { "$" } else { "" },
            r + 1
        ),
        _ => "#REF!".to_string(),
    }
}
