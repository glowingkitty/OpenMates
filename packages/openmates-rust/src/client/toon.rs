//! Bounded native decoder for canonical TOON content, including nested objects,
//! primitive arrays and tabular object arrays. Unknown syntax fails closed.
use super::*;
#[derive(Clone)]
struct Line<'a> {
    indent: usize,
    text: &'a str,
}
pub(super) fn decode(input: &str) -> Result<Value> {
    if input.len() > 16 * 1024 * 1024 {
        return Err(Error::Protocol);
    }
    if let Ok(json) = serde_json::from_str::<Value>(input) {
        return Ok(json);
    }
    let lines = input
        .lines()
        .filter(|l| !l.trim().is_empty())
        .map(|line| {
            let indent = line.len() - line.trim_start_matches(' ').len();
            if line[..indent].contains('\t') || line.trim_start().starts_with('\t') {
                return Err(Error::Protocol);
            }
            Ok(Line {
                indent,
                text: &line[indent..],
            })
        })
        .collect::<Result<Vec<_>>>()?;
    if lines.is_empty() {
        return Ok(json!({}));
    }
    if lines[0].indent != 0 {
        return Err(Error::Protocol);
    }
    let mut cursor = 0;
    let result = object(&lines, &mut cursor, 0, 0)?;
    if cursor != lines.len() {
        return Err(Error::Protocol);
    }
    Ok(result)
}
fn object(lines: &[Line<'_>], cursor: &mut usize, indent: usize, depth: usize) -> Result<Value> {
    if depth > 64 {
        return Err(Error::Protocol);
    }
    let mut result = serde_json::Map::new();
    while *cursor < lines.len() && lines[*cursor].indent == indent {
        let line = lines[*cursor].text;
        let colon = separator(line, ':').ok_or(Error::Protocol)?;
        let header = &line[..colon];
        let rest = line[colon + 1..].trim_start();
        *cursor += 1;
        let (name, array) = header_parts(header)?;
        if result.contains_key(&name) {
            return Err(Error::Protocol);
        }
        let value = if let Some((count, delimiter, columns)) = array {
            if count > 100_000 {
                return Err(Error::Protocol);
            }
            let values = if let Some(columns) = columns {
                if !rest.is_empty() {
                    return Err(Error::Protocol);
                }
                let mut values = vec![];
                for _ in 0..count {
                    let line = lines.get(*cursor).ok_or(Error::Protocol)?;
                    if line.indent <= indent {
                        return Err(Error::Protocol);
                    }
                    let cells = split(line.text, delimiter)?;
                    if cells.len() != columns.len() {
                        return Err(Error::Protocol);
                    }
                    let mut row = serde_json::Map::new();
                    for (name, cell) in columns.iter().zip(cells) {
                        row.insert(name.clone(), primitive(cell)?);
                    }
                    values.push(Value::Object(row));
                    *cursor += 1;
                }
                values
            } else if !rest.is_empty() {
                let cells = split(rest, delimiter)?;
                if cells.len() != count {
                    return Err(Error::Protocol);
                }
                cells
                    .into_iter()
                    .map(primitive)
                    .collect::<Result<Vec<_>>>()?
            } else if count == 0 {
                vec![]
            } else {
                let mut values = vec![];
                for _ in 0..count {
                    let row = lines.get(*cursor).ok_or(Error::Protocol)?;
                    if row.indent <= indent || !row.text.starts_with('-') {
                        return Err(Error::Protocol);
                    }
                    let value = row
                        .text
                        .strip_prefix("- ")
                        .or_else(|| row.text.strip_prefix('-'))
                        .ok_or(Error::Protocol)?;
                    if value.is_empty() {
                        *cursor += 1;
                        let child = lines.get(*cursor).ok_or(Error::Protocol)?;
                        if child.indent <= row.indent {
                            return Err(Error::Protocol);
                        }
                        values.push(object(lines, cursor, child.indent, depth + 1)?);
                    } else if separator(value, ':').is_some() {
                        let base = row.indent;
                        let mut owned = vec![Line {
                            indent: base + 2,
                            text: value,
                        }];
                        let start = *cursor + 1;
                        let mut end = start;
                        while end < lines.len() && lines[end].indent > base {
                            owned.push(lines[end].clone());
                            end += 1;
                        }
                        let mut inner = 0;
                        values.push(object(&owned, &mut inner, base + 2, depth + 1)?);
                        if inner != owned.len() {
                            return Err(Error::Protocol);
                        }
                        *cursor = end;
                    } else {
                        values.push(primitive(value)?);
                        *cursor += 1;
                    }
                }
                values
            };
            Value::Array(values)
        } else if rest.is_empty() {
            if let Some(next) = lines.get(*cursor).filter(|l| l.indent > indent) {
                object(lines, cursor, next.indent, depth + 1)?
            } else {
                json!({})
            }
        } else {
            primitive(rest)?
        };
        result.insert(name, value);
    }
    Ok(Value::Object(result))
}
type ArrayHeader = (usize, char, Option<Vec<String>>);
fn header_parts(header: &str) -> Result<(String, Option<ArrayHeader>)> {
    let header = header.trim();
    let Some(open) = separator(header, '[') else {
        return Ok((name(header)?, None));
    };
    let close = header[open..]
        .find(']')
        .map(|n| open + n)
        .ok_or(Error::Protocol)?;
    let descriptor = &header[open + 1..close];
    let delimiter = if descriptor.ends_with('|') {
        '|'
    } else if descriptor.ends_with('\t') {
        '\t'
    } else {
        ','
    };
    let count_text = descriptor.trim_end_matches(['|', '\t']);
    let count = count_text.parse::<usize>().map_err(|_| Error::Protocol)?;
    let suffix = &header[close + 1..];
    let columns = if suffix.is_empty() {
        None
    } else {
        let body = suffix
            .strip_prefix('{')
            .and_then(|v| v.strip_suffix('}'))
            .ok_or(Error::Protocol)?;
        let fields = split(body, delimiter)?
            .into_iter()
            .map(name)
            .collect::<Result<Vec<_>>>()?;
        let distinct: std::collections::HashSet<_> = fields.iter().collect();
        if distinct.len() != fields.len() {
            return Err(Error::Protocol);
        }
        Some(fields)
    };
    Ok((name(&header[..open])?, Some((count, delimiter, columns))))
}
fn name(value: &str) -> Result<String> {
    let value = value.trim();
    if value.is_empty() {
        return Err(Error::Protocol);
    }
    if value.starts_with('"') {
        serde_json::from_str::<String>(value).map_err(|_| Error::Protocol)
    } else if value.contains(['\n', '\r', ':', '{', '}', '[', ']']) {
        Err(Error::Protocol)
    } else {
        Ok(value.into())
    }
}
fn primitive(value: &str) -> Result<Value> {
    let value = value.trim();
    if value.is_empty() {
        return Err(Error::Protocol);
    }
    if value.starts_with('"') {
        return serde_json::from_str::<String>(value)
            .map(Value::String)
            .map_err(|_| Error::Protocol);
    }
    if value == "true" {
        return Ok(json!(true));
    }
    if value == "false" {
        return Ok(json!(false));
    }
    if value == "null" {
        return Ok(Value::Null);
    }
    if let Ok(v) = serde_json::from_str::<serde_json::Number>(value) {
        return Ok(Value::Number(v));
    }
    if value.contains(['"', '\n', '\r']) {
        return Err(Error::Protocol);
    }
    Ok(json!(value))
}
fn separator(value: &str, wanted: char) -> Option<usize> {
    let mut quote = false;
    let mut escape = false;
    for (i, c) in value.char_indices() {
        if escape {
            escape = false;
            continue;
        }
        if c == '\\' && quote {
            escape = true;
            continue;
        }
        if c == '"' {
            quote = !quote;
            continue;
        }
        if c == wanted && !quote {
            return Some(i);
        }
    }
    None
}
fn split(value: &str, delimiter: char) -> Result<Vec<&str>> {
    let mut result = vec![];
    let mut quote = false;
    let mut escape = false;
    let mut start = 0;
    for (i, c) in value.char_indices() {
        if escape {
            escape = false;
            continue;
        }
        if c == '\\' && quote {
            escape = true;
            continue;
        }
        if c == '"' {
            quote = !quote;
            continue;
        }
        if c == delimiter && !quote {
            result.push(value[start..i].trim());
            start = i + c.len_utf8()
        }
    }
    if quote || escape {
        return Err(Error::Protocol);
    }
    result.push(value[start..].trim());
    Ok(result)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn canonical_embeds() {
        assert_eq!(
            decode("type: code\ncode: \"hello\\nworld\"\nlanguage: rust").unwrap(),
            json!({"type":"code","code":"hello\nworld","language":"rust"})
        );
    }
    #[test]
    fn nested_tabular_and_list_arrays() {
        assert_eq!(decode("title: Results\nitems[2]{name,score}:\n  alice,1\n  \"bob, jr\",2\nconfig:\n  enabled: true\ntags[2]: a,b\nempty[0]:").unwrap(),json!({"title":"Results","items":[{"name":"alice","score":1},{"name":"bob, jr","score":2}],"config":{"enabled":true},"tags":["a","b"],"empty":[]}));
    }
    #[test]
    fn malformed_is_never_silently_truncated() {
        for bad in [
            "x[2]: a",
            "x: one\nx: two",
            "x[1]{a,b}:\n  one",
            "x: \"unterminated",
        ] {
            assert!(decode(bad).is_err());
        }
    }
}
