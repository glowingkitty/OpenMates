//! JSON.parse data semantics with lossless UTF-16 and explicit CLI/SDK writers.
//! serde_json owns the grammar, including raw object keys and escaped bytes.
//! No runtime evaluation, unchecked grammar, serde Value string conversion or
//! fallback crypto/authority is involved. App-owned scratch is bounded/wiped;
//! serde_json private parser scratch follows that trusted library's allocator
//! lifetime and is not claimed to be externally zeroized.
use super::*;
use serde::de::{MapAccess, Visitor};
use std::collections::BTreeMap;
const MAX_INPUT: usize = 256 * 1024; // Existing selected encrypted-page byte bound.
const MAX_DEPTH: usize = 128; // serde_json's ordinary structured recursion bound.
const MAX_OUTPUT: usize = MAX_INPUT * 6 + 2; // Worst-case UTF-16 escaping expansion (lone/control units).

#[derive(PartialEq, Eq, PartialOrd, Ord)]
pub struct ChatDetailsJsonString(Vec<u16>);
impl ChatDetailsJsonString {
    pub fn utf16_units(&self) -> &[u16] {
        &self.0
    }
}
impl Wipe for ChatDetailsJsonString {
    fn wipe(&mut self) {
        self.0.zeroize();
    }
}
impl Drop for ChatDetailsJsonString {
    fn drop(&mut self) {
        self.wipe();
    }
}

/// JS JSON.parse value. Numbers are binary64, including overflow infinities and
/// signed zero. Object keys and strings are exact UTF-16 units; object entries
/// have ECMAScript own-property enumeration order after last-definition wins.
#[derive(PartialEq)]
pub enum ChatDetailsJsonValue {
    Null,
    Bool(bool),
    Number(f64),
    String(ChatDetailsJsonString),
    Array(Vec<ChatDetailsJsonValue>),
    Object(Vec<(ChatDetailsJsonString, ChatDetailsJsonValue)>),
}
impl Wipe for ChatDetailsJsonValue {
    fn wipe(&mut self) {
        match self {
            Self::Null => {}
            Self::Bool(v) => v.zeroize(),
            Self::Number(v) => v.zeroize(),
            Self::String(v) => v.wipe(),
            Self::Array(v) => v.wipe(),
            Self::Object(v) => {
                for (key, value) in v {
                    key.wipe();
                    value.wipe();
                }
            }
        }
    }
}
impl Drop for ChatDetailsJsonValue {
    fn drop(&mut self) {
        // Recursive owned children drop themselves; do not recursively wipe a
        // second time at every depth. String leaves own zeroizing UTF-16.
        match self {
            Self::Number(v) => v.zeroize(),
            Self::Bool(v) => v.zeroize(),
            _ => {}
        }
    }
}

pub struct ChatDetailsJson {
    value: ChatDetailsJsonValue,
}
impl ChatDetailsJson {
    pub(super) fn from_text(text: String) -> Result<Self> {
        let text = Zeroizing::new(text);
        if text.len() > MAX_INPUT {
            return Err(Error::Protocol);
        }
        let raw: &serde_json::value::RawValue = serde_json::from_str(&text)?;
        let mut remaining = MAX_INPUT;
        Ok(Self {
            value: parse(raw, 0, &mut remaining)?,
        })
    }
    pub fn value(&self) -> &ChatDetailsJsonValue {
        &self.value
    }
    /// CLI JSON.stringify projection: nonfinite numbers become null, -0 is 0.
    pub fn encoded_json(&self) -> Result<String> {
        self.encode(false).map(|mut v| std::mem::take(&mut *v))
    }
    /// Valid JSON text which materializes equivalent raw SDK numbers in npm and
    /// Python: infinities use ±1e400, and negative zero uses -0.0.
    pub fn sdk_encoded_json(&self) -> Result<String> {
        self.encode(true).map(|mut v| std::mem::take(&mut *v))
    }
    fn encode(&self, sdk: bool) -> Result<Zeroizing<String>> {
        let mut output = Zeroizing::new(String::new());
        write_value(&self.value, sdk, &mut output)?;
        // Validate generated JSON through the same trusted library grammar.
        let _: &serde_json::value::RawValue = serde_json::from_str(&output)?;
        Ok(output)
    }
    fn serialize_mode<S: serde::Serializer>(
        &self,
        sdk: bool,
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        let text = self.encode(sdk).map_err(serde::ser::Error::custom)?;
        let raw: &serde_json::value::RawValue =
            serde_json::from_str(&text).map_err(serde::ser::Error::custom)?;
        raw.serialize(serializer)
    }
}
impl Wipe for ChatDetailsJson {
    fn wipe(&mut self) {
        self.value.wipe();
    }
}
impl Drop for ChatDetailsJson {
    fn drop(&mut self) {
        self.wipe();
    }
}
impl Serialize for ChatDetailsJson {
    fn serialize<S: serde::Serializer>(
        &self,
        serializer: S,
    ) -> std::result::Result<S::Ok, S::Error> {
        self.serialize_mode(false, serializer)
    }
}
impl<'de> Deserialize<'de> for ChatDetailsJson {
    fn deserialize<D: serde::Deserializer<'de>>(
        deserializer: D,
    ) -> std::result::Result<Self, D::Error> {
        let raw = Box::<serde_json::value::RawValue>::deserialize(deserializer)?;
        let text: Box<str> = raw.into();
        Self::from_text(text.into_string())
            .map_err(|_| serde::de::Error::custom("Invalid bounded chat-details JSON."))
    }
}
pub(super) struct ModeJson<'a>(pub(super) &'a ChatDetailsJson, pub(super) bool);
impl Serialize for ModeJson<'_> {
    fn serialize<S: serde::Serializer>(&self, s: S) -> std::result::Result<S::Ok, S::Error> {
        self.0.serialize_mode(self.1, s)
    }
}

// MapKey::deserialize_newtype_struct explicitly delegates RawValue keys to the
// checked serde_json parser. This avoids String's rejection of lone surrogates.
struct RawObject<'a>(
    Vec<(
        &'a serde_json::value::RawValue,
        &'a serde_json::value::RawValue,
    )>,
);
impl<'de> Deserialize<'de> for RawObject<'de> {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> std::result::Result<Self, D::Error> {
        struct ObjectVisitor;
        impl<'de> Visitor<'de> for ObjectVisitor {
            type Value = RawObject<'de>;
            fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
                f.write_str("JSON object")
            }
            fn visit_map<M: MapAccess<'de>>(
                self,
                mut map: M,
            ) -> std::result::Result<Self::Value, M::Error> {
                let mut rows = Vec::new();
                while let Some(row)=map.next_entry::<&'de serde_json::value::RawValue,&'de serde_json::value::RawValue>()?{rows.push(row);}
                Ok(RawObject(rows))
            }
        }
        d.deserialize_map(ObjectVisitor)
    }
}
struct Bytes(Zeroizing<Vec<u8>>);
impl<'de> Deserialize<'de> for Bytes {
    fn deserialize<D: serde::Deserializer<'de>>(d: D) -> std::result::Result<Self, D::Error> {
        struct BytesVisitor;
        impl<'de> Visitor<'de> for BytesVisitor {
            type Value = Bytes;
            fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
                f.write_str("checked JSON string bytes")
            }
            fn visit_bytes<E: serde::de::Error>(self, v: &[u8]) -> std::result::Result<Bytes, E> {
                Ok(Bytes(Zeroizing::new(v.to_vec())))
            }
            fn visit_byte_buf<E: serde::de::Error>(
                self,
                v: Vec<u8>,
            ) -> std::result::Result<Bytes, E> {
                Ok(Bytes(Zeroizing::new(v)))
            }
        }
        d.deserialize_byte_buf(BytesVisitor)
    }
}
fn string(raw: &serde_json::value::RawValue) -> Result<ChatDetailsJsonString> {
    let Bytes(bytes) = serde_json::from_str::<Bytes>(raw.get())?;
    let mut units = ChatDetailsJsonString(vec![]);
    let mut at = 0;
    while at < bytes.len() {
        let first = bytes[at];
        let (width, mut cp) = match first {
            0..=0x7f => (1, u32::from(first)),
            0xc2..=0xdf => (2, u32::from(first & 0x1f)),
            0xe0..=0xef => (3, u32::from(first & 0x0f)),
            0xf0..=0xf4 => (4, u32::from(first & 7)),
            _ => return Err(Error::Protocol),
        };
        if at + width > bytes.len() {
            return Err(Error::Protocol);
        }
        for byte in &bytes[at + 1..at + width] {
            if byte & 0xc0 != 0x80 {
                return Err(Error::Protocol);
            }
            cp = (cp << 6) | u32::from(byte & 0x3f);
        }
        if (width == 2 && cp < 0x80)
            || (width == 3 && cp < 0x800)
            || (width == 4 && !(0x10000..=0x10ffff).contains(&cp))
        {
            return Err(Error::Protocol);
        }
        // serde_json byte-string parsing intentionally permits WTF-8 surrogate
        // codepoints, so preserve those exact units rather than UTF-8 conversion.
        if cp <= 0xffff {
            units.0.push(cp as u16);
        } else {
            let n = cp - 0x10000;
            units.0.push(0xd800 + (n >> 10) as u16);
            units.0.push(0xdc00 + (n & 1023) as u16);
        }
        at += width;
    }
    Ok(units)
}
fn index(key: &ChatDetailsJsonString) -> Option<u32> {
    let u = &key.0;
    if u.is_empty() || u.len() > 10 || (u.len() > 1 && u[0] == u16::from(b'0')) {
        return None;
    }
    let mut n = 0u64;
    for c in u {
        if !(u16::from(b'0')..=u16::from(b'9')).contains(c) {
            return None;
        }
        n = n * 10 + u64::from(*c - u16::from(b'0'));
    }
    (n < u64::from(u32::MAX)).then_some(n as u32)
}
fn parse(
    raw: &serde_json::value::RawValue,
    depth: usize,
    remaining: &mut usize,
) -> Result<ChatDetailsJsonValue> {
    if depth >= MAX_DEPTH || *remaining == 0 {
        return Err(Error::Protocol);
    }
    *remaining -= 1;
    let text = raw.get();
    let first = text.as_bytes().first().ok_or(Error::Protocol)?;
    Ok(match first {
        b'n' => ChatDetailsJsonValue::Null,
        b't' => ChatDetailsJsonValue::Bool(true),
        b'f' => ChatDetailsJsonValue::Bool(false),
        b'"' => ChatDetailsJsonValue::String(string(raw)?),
        b'[' => {
            let values: Vec<&serde_json::value::RawValue> = serde_json::from_str(text)?;
            let mut output = Vec::new();
            for value in values {
                output.push(parse(value, depth + 1, remaining)?);
            }
            ChatDetailsJsonValue::Array(output)
        }
        b'{' => {
            let RawObject(values) = serde_json::from_str::<RawObject<'_>>(text)?;
            let mut object =
                BTreeMap::<ChatDetailsJsonString, (usize, ChatDetailsJsonValue)>::new();
            for (raw_key, value) in values {
                let key = string(raw_key)?;
                let value = parse(value, depth + 1, remaining)?;
                let next = object.len();
                match object.entry(key) {
                    std::collections::btree_map::Entry::Occupied(mut old) => {
                        old.get_mut().1 = value;
                    }
                    std::collections::btree_map::Entry::Vacant(slot) => {
                        slot.insert((next, value));
                    }
                }
            }
            let mut entries = object
                .into_iter()
                .map(|(key, (order, value))| (key, order, value))
                .collect::<Vec<_>>();
            entries.sort_by(|(a, oa, _), (b, ob, _)| match (index(a), index(b)) {
                (Some(a), Some(b)) => a.cmp(&b),
                (Some(_), None) => std::cmp::Ordering::Less,
                (None, Some(_)) => std::cmp::Ordering::Greater,
                (None, None) => oa.cmp(ob),
            });
            ChatDetailsJsonValue::Object(
                entries
                    .into_iter()
                    .map(|(key, _, value)| (key, value))
                    .collect(),
            )
        }
        _ => ChatDetailsJsonValue::Number(text.parse::<f64>().map_err(|_| Error::Protocol)?),
    })
}
fn push(output: &mut String, text: &str) -> Result<()> {
    if output
        .len()
        .checked_add(text.len())
        .is_none_or(|len| len > MAX_OUTPUT)
    {
        return Err(Error::Protocol);
    }
    output.push_str(text);
    Ok(())
}
// The same checked UTF-16 writer serves PII values/keys and draft previews.
// Scalar runs use serde_json's formatter; only unpaired units need the fixed
// six-byte escape. No full UTF-8 plaintext copy is retained or allocated.
pub(super) fn write_utf16_string(units: &[u16], out: &mut String) -> Result<()> {
    use serde_json::ser::{CharEscape, CompactFormatter, Formatter};
    use std::io::{self, Write};
    struct BoundedString<'a>(&'a mut String);
    impl Write for BoundedString<'_> {
        fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
            if self.0.len().checked_add(bytes.len()).is_none_or(|n| n > MAX_OUTPUT) {
                return Err(io::Error::from(io::ErrorKind::InvalidData));
            }
            let text = std::str::from_utf8(bytes)
                .map_err(|_| io::Error::from(io::ErrorKind::InvalidData))?;
            self.0.push_str(text);
            Ok(bytes.len())
        }
        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }
    fn flush_run(
        writer: &mut BoundedString<'_>,
        formatter: &mut CompactFormatter,
        buffer: &mut [u8],
        used: &mut usize,
    ) -> io::Result<()> {
        let text = std::str::from_utf8(&buffer[..*used])
            .map_err(|_| io::Error::from(io::ErrorKind::InvalidData))?;
        formatter.write_string_fragment(writer, text)?;
        buffer[..*used].zeroize();
        *used = 0;
        Ok(())
    }
    let mut writer = BoundedString(out);
    let mut formatter = CompactFormatter;
    let mut buffer = Zeroizing::new([0u8; 256]);
    let mut used = 0;
    (|| -> io::Result<()> {
        formatter.begin_string(&mut writer)?;
        for decoded in char::decode_utf16(units.iter().copied()) {
            let scalar = match decoded {
                Ok(scalar) => scalar,
                Err(lone) => {
                    flush_run(&mut writer, &mut formatter, &mut *buffer, &mut used)?;
                    let unit = lone.unpaired_surrogate();
                    const HEX: &[u8; 16] = b"0123456789abcdef";
                    let mut escape = Zeroizing::new(*b"\\u0000");
                    for (at, shift) in [12, 8, 4, 0].into_iter().enumerate() {
                        escape[at + 2] = HEX[usize::from((unit >> shift) & 15)];
                    }
                    writer.write_all(&*escape)?;
                    continue;
                }
            };
            let escape = match scalar {
                '"' => Some(CharEscape::Quote),
                '\\' => Some(CharEscape::ReverseSolidus),
                '\u{08}' => Some(CharEscape::Backspace),
                '\u{09}' => Some(CharEscape::Tab),
                '\u{0a}' => Some(CharEscape::LineFeed),
                '\u{0c}' => Some(CharEscape::FormFeed),
                '\u{0d}' => Some(CharEscape::CarriageReturn),
                c if c <= '\u{1f}' => Some(CharEscape::AsciiControl(c as u8)),
                _ => None,
            };
            if let Some(escape) = escape {
                flush_run(&mut writer, &mut formatter, &mut *buffer, &mut used)?;
                formatter.write_char_escape(&mut writer, escape)?;
            } else {
                if used + scalar.len_utf8() > buffer.len() {
                    flush_run(&mut writer, &mut formatter, &mut *buffer, &mut used)?;
                }
                used += scalar.encode_utf8(&mut buffer[used..]).len();
            }
        }
        flush_run(&mut writer, &mut formatter, &mut *buffer, &mut used)?;
        formatter.end_string(&mut writer)
    })()
    .map_err(|_| Error::Protocol)
}
fn write_string(value: &ChatDetailsJsonString, out: &mut String) -> Result<()> {
    write_utf16_string(&value.0, out)
}
fn number(value: f64, sdk: bool) -> Result<Zeroizing<String>> {
    if !value.is_finite() {
        return Ok(Zeroizing::new(if !sdk {
            "null".into()
        } else if value.is_sign_negative() {
            "-1e400".into()
        } else {
            "1e400".into()
        }));
    }
    if value == 0.0 {
        return Ok(Zeroizing::new(if sdk && value.is_sign_negative() {
            "-0.0".into()
        } else {
            "0".into()
        }));
    }
    if sdk && (value.fract() != 0.0 || value.abs() >= 9_007_199_254_740_992.0) {
        // Python's JSON loader preserves integral lexical tokens as arbitrary
        // integers. Force its binary64 path when a JS shortest integer spelling
        // can denote a different mathematical integer (e.g.1000000000000000100).
        // Small exact integral tokens remain compatible with the existing API.
        let mut token = Zeroizing::new(serde_json::to_string(&value)?);
        if !token.contains('.') && !token.contains('e') {
            token.push_str(".0");
        }
        return Ok(token);
    }
    // Reuse serde_json's pinned shortest correctly-rounded f64 formatter; adapt
    // only its decimal/exponent layout and integral .0 to JS Number spelling.
    // This is trusted formatter output, not parsing an unchecked JSON grammar.
    let token = Zeroizing::new(serde_json::to_string(&value)?);
    let negative = token.starts_with('-');
    let mantissa = token.strip_prefix('-').unwrap_or(&token);
    let (mantissa, exponent) = match mantissa.split_once('e') {
        Some((m, e)) => (m, e.parse::<i32>().map_err(|_| Error::Protocol)?),
        None => (mantissa, 0),
    };
    let mut position = mantissa.find('.').unwrap_or(mantissa.len()) as i32 + exponent;
    let mut digits = Zeroizing::new(
        mantissa
            .bytes()
            .filter(|c| *c != b'.')
            .map(char::from)
            .collect::<String>(),
    );
    while digits.starts_with('0') && digits.len() > 1 {
        digits.remove(0);
        position -= 1;
    }
    while digits.ends_with('0') && digits.len() > 1 {
        digits.pop();
    }
    let mut out = Zeroizing::new(String::new());
    if negative {
        out.push('-');
    }
    if position > 0 && position <= 21 {
        let position = position as usize;
        if digits.len() <= position {
            out.push_str(&digits);
            out.extend(std::iter::repeat_n('0', position - digits.len()));
        } else {
            out.push_str(&digits[..position]);
            out.push('.');
            out.push_str(&digits[position..]);
        }
    } else if position <= 0 && position > -6 {
        out.push_str("0.");
        out.extend(std::iter::repeat_n('0', (-position) as usize));
        out.push_str(&digits);
    } else {
        out.push(digits.as_bytes()[0] as char);
        if digits.len() > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        out.push('e');
        let exponent = position - 1;
        if exponent >= 0 {
            out.push('+');
        }
        out.push_str(&exponent.to_string());
    }
    Ok(out)
}
fn write_value(value: &ChatDetailsJsonValue, sdk: bool, out: &mut String) -> Result<()> {
    match value {
        ChatDetailsJsonValue::Null => push(out, "null"),
        ChatDetailsJsonValue::Bool(v) => push(out, if *v { "true" } else { "false" }),
        ChatDetailsJsonValue::Number(v) => push(out, &number(*v, sdk)?),
        ChatDetailsJsonValue::String(v) => write_string(v, out),
        ChatDetailsJsonValue::Array(values) => {
            push(out, "[")?;
            for (i, value) in values.iter().enumerate() {
                if i > 0 {
                    push(out, ",")?;
                }
                write_value(value, sdk, out)?;
            }
            push(out, "]")
        }
        ChatDetailsJsonValue::Object(values) => {
            push(out, "{")?;
            for (i, (key, value)) in values.iter().enumerate() {
                if i > 0 {
                    push(out, ",")?;
                }
                write_string(key, out)?;
                push(out, ":")?;
                write_value(value, sdk, out)?;
            }
            push(out, "}")
        }
    }
}
