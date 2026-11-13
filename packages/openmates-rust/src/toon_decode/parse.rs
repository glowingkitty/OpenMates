//! Recursive-descent TOON decoder (port of 4.4.0 `decoders.ts` with
//! `strict: false` and the event builder folded in). Mirrors the TS control
//! flow line by line: which construct each line opens, when a block ends
//! (depth at or below its parent), and which mismatches still throw in
//! non-strict mode (over-indented siblings, cell-count mismatches, trailing
//! content after a root array).
use super::header::{Field, Header, HeaderLine, count_leaf_fields, parse_header_line};
use super::scan::{
    Line, find_unquoted, is, is_array_header_content, is_data_row, is_key_value, parse_delimited,
    parse_key_token, parse_primitive, trim_spaces,
};
use super::value::{ToonObject, ToonValue};
use super::{MAX_NESTING, ToonDecodeError};

/// Owns the scanned lines and the read position (the TS line reader).
pub(super) struct Decoder {
    lines: Vec<Line>,
    position: usize,
    nesting: usize,
}

impl Decoder {
    pub(super) fn new(lines: Vec<Line>) -> Self {
        Self {
            lines,
            position: 0,
            nesting: 0,
        }
    }

    fn peek(&self) -> Option<&Line> {
        self.lines.get(self.position)
    }

    fn peek_depth(&self) -> Option<usize> {
        self.peek().map(|line| line.depth)
    }

    /// Consumes the next line; the content is moved out (each line is read once).
    fn read(&mut self) -> Option<(Vec<char>, usize)> {
        let line = self.lines.get_mut(self.position)?;
        self.position += 1;
        Some((std::mem::take(&mut line.content), line.number))
    }

    fn over_indented(&self) -> ToonDecodeError {
        let line = self.peek().map_or(0, |line| line.number);
        ToonDecodeError::at("over-indented line", line)
    }

    fn enter(&mut self) -> Result<(), ToonDecodeError> {
        self.nesting += 1;
        if self.nesting > MAX_NESTING {
            return Err(ToonDecodeError::new("nesting too deep"));
        }
        Ok(())
    }

    fn leave(&mut self) {
        self.nesting -= 1;
    }

    /// `decodeDocument`.
    pub(super) fn decode_document(mut self) -> Result<ToonValue, ToonDecodeError> {
        let Some(first) = self.peek() else {
            return Ok(ToonValue::Object(ToonObject::default()));
        };
        if first.depth != 0 {
            return Err(self.over_indented());
        }
        if is(trim_spaces(&first.content), "[]") {
            self.read();
            return self.fully_consumed(ToonValue::Array(Vec::new()));
        }
        if is_array_header_content(&first.content) {
            let parsed = parse_header_line(&first.content)
                .map_err(|error| with_line(error, first.number))?;
            if let HeaderLine::Header(header, inline) = parsed {
                self.read();
                let value = self.decode_array_from_header(header, inline.as_deref(), 0)?;
                return self.fully_consumed(value);
            }
        }
        let Some((first, number)) = self.read() else {
            return Ok(ToonValue::Object(ToonObject::default()));
        };
        let following = self.peek_depth();
        if following.is_none() && !is_key_value(&first) {
            return parse_primitive(&first).map_err(|error| with_line(error, number));
        }
        if !is_key_value(&first) && following == Some(0) {
            return Err(ToonDecodeError::at(
                "top-level line is neither key-value nor array header",
                number,
            ));
        }
        let mut root = ToonObject::default();
        self.decode_key_value(&first, number, 0, &mut root)?;
        while let Some(depth) = self.peek_depth() {
            if depth != 0 {
                return Err(self.over_indented());
            }
            let Some((content, number)) = self.read() else {
                break;
            };
            self.decode_key_value(&content, number, 0, &mut root)?;
        }
        Ok(ToonValue::Object(root))
    }

    /// `assertFullyConsumed` after a root array.
    fn fully_consumed(&self, value: ToonValue) -> Result<ToonValue, ToonDecodeError> {
        match self.peek() {
            Some(line) => Err(ToonDecodeError::at(
                "content after the document root",
                line.number,
            )),
            None => Ok(value),
        }
    }

    /// `decodeKeyValue`: one `key: ...` / `key[N]...:` line into `target`.
    fn decode_key_value(
        &mut self,
        content: &[char],
        number: usize,
        base_depth: usize,
        target: &mut ToonObject,
    ) -> Result<(), ToonDecodeError> {
        if let HeaderLine::Header(header, inline) =
            parse_header_line(content).map_err(|error| with_line(error, number))?
        {
            let Some(key) = header.key.clone() else {
                return Err(ToonDecodeError::at(
                    "keyless array header outside the root or a list item",
                    number,
                ));
            };
            let value = self.decode_array_from_header(header, inline.as_deref(), base_depth)?;
            target.set(key, value);
            return Ok(());
        }
        let (key, end) = parse_key_token(content).map_err(|error| with_line(error, number))?;
        let rest = trim_spaces(&content[end..]);
        let value = if rest.is_empty() {
            match self.peek_depth() {
                Some(depth) if depth > base_depth => {
                    self.enter()?;
                    let fields = self.decode_object_fields(base_depth + 1)?;
                    self.leave();
                    ToonValue::Object(fields)
                }
                _ => ToonValue::Object(ToonObject::default()),
            }
        } else if is(rest, "[]") {
            ToonValue::Array(Vec::new())
        } else {
            parse_primitive(rest).map_err(|error| with_line(error, number))?
        };
        target.set(key, value);
        Ok(())
    }

    /// `decodeObjectFields`: siblings share the first child's depth.
    fn decode_object_fields(&mut self, base_depth: usize) -> Result<ToonObject, ToonDecodeError> {
        let mut object = ToonObject::default();
        let mut computed: Option<usize> = None;
        while let Some(depth) = self.peek_depth() {
            if depth < base_depth {
                break;
            }
            let expected = *computed.get_or_insert(depth);
            if depth != expected {
                return Err(self.over_indented());
            }
            let Some((content, number)) = self.read() else {
                break;
            };
            self.decode_key_value(&content, number, expected, &mut object)?;
        }
        Ok(object)
    }

    /// `scopeContentDepth` (non-strict: a deeper first line sets the depth).
    fn scope_content_depth(&self, base_depth: usize) -> usize {
        match self.peek_depth() {
            Some(depth) if depth > base_depth + 1 => depth,
            _ => base_depth + 1,
        }
    }

    /// `decodeArrayFromHeader`.
    fn decode_array_from_header(
        &mut self,
        header: Header,
        inline: Option<&[char]>,
        base_depth: usize,
    ) -> Result<ToonValue, ToonDecodeError> {
        self.enter()?;
        let value = if header.keyed {
            ToonValue::Object(self.decode_keyed_object(&header, base_depth)?)
        } else if let Some(inline) = inline {
            ToonValue::Array(primitives(&parse_delimited(inline, header.delimiter))?)
        } else if header
            .fields
            .as_ref()
            .is_some_and(|fields| !fields.is_empty())
        {
            ToonValue::Array(self.decode_tabular_array(&header, base_depth)?)
        } else {
            ToonValue::Array(self.decode_list_array(base_depth)?)
        };
        self.leave();
        Ok(value)
    }

    /// `decodeKeyedObject`: `key: c1,c2` entry rows of a `[N:]{...}` header.
    fn decode_keyed_object(
        &mut self,
        header: &Header,
        base_depth: usize,
    ) -> Result<ToonObject, ToonDecodeError> {
        let fields = header.fields.as_deref().unwrap_or_default();
        let entry_depth = self.scope_content_depth(base_depth);
        let leaf_count = count_leaf_fields(fields);
        let mut object = ToonObject::default();
        while let Some(line) = self.peek() {
            if line.depth <= base_depth {
                break;
            }
            if line.depth != entry_depth {
                return Err(self.over_indented());
            }
            if find_unquoted(&line.content, ':', 0).is_none() {
                return Err(ToonDecodeError::at(
                    "expected entry row inside keyed tabular object",
                    line.number,
                ));
            }
            let Some((content, number)) = self.read() else {
                break;
            };
            let (key, end) = parse_key_token(&content).map_err(|error| with_line(error, number))?;
            let cells = trim_spaces(&content[end..]);
            let values = if cells.is_empty() {
                Vec::new()
            } else {
                parse_delimited(cells, header.delimiter)
            };
            if values.len() != leaf_count {
                return Err(ToonDecodeError::at(
                    "keyed entry cell count mismatch",
                    number,
                ));
            }
            let row = primitives(&values).map_err(|error| with_line(error, number))?;
            object.set(
                key,
                ToonValue::Object(object_from_fields(fields, &mut row.into_iter())),
            );
        }
        Ok(object)
    }

    /// `decodeTabularArray` (non-strict: rows until a non-row line).
    fn decode_tabular_array(
        &mut self,
        header: &Header,
        base_depth: usize,
    ) -> Result<Vec<ToonValue>, ToonDecodeError> {
        let fields = header.fields.as_deref().unwrap_or_default();
        let leaf_count = count_leaf_fields(fields);
        let row_depth = self.scope_content_depth(base_depth);
        let mut rows = Vec::new();
        while let Some(line) = self.peek() {
            if line.depth <= base_depth {
                break;
            }
            if line.depth != row_depth {
                return Err(self.over_indented());
            }
            if !is_data_row(&line.content, header.delimiter) {
                break;
            }
            let Some((content, number)) = self.read() else {
                break;
            };
            let values = parse_delimited(&content, header.delimiter);
            if values.len() != leaf_count {
                return Err(ToonDecodeError::at(
                    "tabular row value count mismatch",
                    number,
                ));
            }
            let row = primitives(&values).map_err(|error| with_line(error, number))?;
            rows.push(ToonValue::Object(object_from_fields(
                fields,
                &mut row.into_iter(),
            )));
        }
        Ok(rows)
    }

    /// `decodeListArray` (non-strict: items until a non-item line).
    fn decode_list_array(&mut self, base_depth: usize) -> Result<Vec<ToonValue>, ToonDecodeError> {
        let item_depth = self.scope_content_depth(base_depth);
        let mut items = Vec::new();
        while let Some(line) = self.peek() {
            if line.depth <= base_depth {
                break;
            }
            if line.depth != item_depth {
                return Err(self.over_indented());
            }
            if !(line.content.starts_with(&['-', ' ']) || is(&line.content, "-")) {
                break;
            }
            items.push(self.decode_list_item(item_depth)?);
        }
        Ok(items)
    }

    /// `decodeListItem`: `-` / `- value` / `- key: ...` / `- [N]...` items.
    fn decode_list_item(&mut self, base_depth: usize) -> Result<ToonValue, ToonDecodeError> {
        let Some((content, number)) = self.read() else {
            return Err(ToonDecodeError::new("expected list item"));
        };
        if is(&content, "-") {
            return Ok(ToonValue::Object(ToonObject::default()));
        }
        let after: Vec<char> = content[2..]
            .iter()
            .copied()
            .skip_while(|c| *c == ' ')
            .collect();
        if trim_spaces(&after).is_empty() {
            return Ok(ToonValue::Object(ToonObject::default()));
        }
        if is(trim_spaces(&after), "[]") {
            return Ok(ToonValue::Array(Vec::new()));
        }
        let parsed = parse_header_line(&after).map_err(|error| with_line(error, number))?;
        if let HeaderLine::Header(header, inline) = parsed {
            if is_array_header_content(&after) {
                if header.keyed || header.fields.is_some() {
                    return Err(ToonDecodeError::at(
                        "keyless keyed or field header inside a list item",
                        number,
                    ));
                }
                return self.decode_array_from_header(header, inline.as_deref(), base_depth);
            }
            if let Some(key) = header.key.clone().filter(|_| header.fields.is_some()) {
                self.enter()?;
                let mut object = ToonObject::default();
                let value =
                    self.decode_array_from_header(header, inline.as_deref(), base_depth + 1)?;
                object.set(key, value);
                self.follow_sibling_fields(base_depth + 1, &mut object)?;
                self.leave();
                return Ok(ToonValue::Object(object));
            }
        }
        if is_key_value(&after) {
            self.enter()?;
            let mut object = ToonObject::default();
            self.decode_key_value(&after, number, base_depth + 1, &mut object)?;
            self.follow_sibling_fields(base_depth + 1, &mut object)?;
            self.leave();
            return Ok(ToonValue::Object(object));
        }
        parse_primitive(&after).map_err(|error| with_line(error, number))
    }

    /// `followSiblingFields`: further fields of a list-item object.
    fn follow_sibling_fields(
        &mut self,
        depth: usize,
        object: &mut ToonObject,
    ) -> Result<(), ToonDecodeError> {
        while let Some(line_depth) = self.peek_depth() {
            if line_depth < depth {
                break;
            }
            if line_depth != depth {
                return Err(self.over_indented());
            }
            let Some((content, number)) = self.read() else {
                break;
            };
            self.decode_key_value(&content, number, depth, object)?;
        }
        Ok(())
    }
}

fn with_line(error: ToonDecodeError, line: usize) -> ToonDecodeError {
    ToonDecodeError {
        line: error.line.or(Some(line)),
        ..error
    }
}

fn primitives(values: &[Vec<char>]) -> Result<Vec<ToonValue>, ToonDecodeError> {
    values.iter().map(|value| parse_primitive(value)).collect()
}

/// `yieldObjectFromFields`: cells assigned to leaf fields depth-first. The
/// callers checked the cell count against `count_leaf_fields`, so the
/// iterator never runs dry (a missing cell would read `null`, never panic).
fn object_from_fields(fields: &[Field], cells: &mut impl Iterator<Item = ToonValue>) -> ToonObject {
    let mut object = ToonObject::default();
    for field in fields {
        let value = match &field.children {
            Some(children) => ToonValue::Object(object_from_fields(children, cells)),
            None => cells.next().unwrap_or(ToonValue::Null),
        };
        object.set(field.name.clone(), value);
    }
    object
}
