//! Insertion-ordered JSON for the workflow `work` ops (shared Rust core Worker).
//!
//! spec: specifications/features/workflows#workflows.portability.definition-roundtrip
//!
//! `serde_json::Value` sorts object keys, but the workflow ops must walk and
//! return objects in JavaScript `Object.entries` order: the portability check
//! reports the first offending key, and the template payload is encrypted from
//! its `JSON.stringify` text. The page's `JSON.stringify` already bakes that
//! order into the input text, so [`Tree`] keeps it and writes it back verbatim.

use serde::de::{Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};
use serde::ser::{Serialize, SerializeMap, SerializeSeq, Serializer};
use serde_json::{Number, Value};
use std::fmt;

/// A JSON value that keeps object key order (JS insertion order).
#[derive(Debug, Clone, PartialEq)]
pub(crate) enum Tree {
    Null,
    Bool(bool),
    Num(Number),
    Str(String),
    Arr(Vec<Tree>),
    Obj(Vec<(String, Tree)>),
}

impl Tree {
    /// An empty object (`{}`).
    pub(crate) fn object() -> Tree {
        Tree::Obj(Vec::new())
    }

    /// `value[key]` of an object; `None` (JS `undefined`) for a missing key or a non-object.
    pub(crate) fn get(&self, key: &str) -> Option<&Tree> {
        match self {
            Tree::Obj(entries) => entries.iter().find(|(k, _)| k == key).map(|(_, v)| v),
            _ => None,
        }
    }

    /// The text of a string value.
    pub(crate) fn as_str(&self) -> Option<&str> {
        match self {
            Tree::Str(s) => Some(s),
            _ => None,
        }
    }

    /// JS `obj[key] = value`: an existing key keeps its position, a new one is appended.
    pub(crate) fn set(&mut self, key: &str, value: Tree) {
        if let Tree::Obj(entries) = self {
            match entries.iter_mut().find(|(k, _)| k == key) {
                Some(entry) => entry.1 = value,
                None => entries.push((key.to_owned(), value)),
            }
        }
    }

    /// `obj[key] = value` only when `value` is defined (JSON drops `undefined` members).
    pub(crate) fn set_defined(&mut self, key: &str, value: Option<&Tree>) {
        if let Some(value) = value {
            self.set(key, value.clone());
        }
    }

    /// The plain `serde_json` value (for helpers such as `String(value)`).
    pub(crate) fn to_value(&self) -> Value {
        match self {
            Tree::Null => Value::Null,
            Tree::Bool(b) => Value::Bool(*b),
            Tree::Num(n) => Value::Number(n.clone()),
            Tree::Str(s) => Value::String(s.clone()),
            Tree::Arr(items) => Value::Array(items.iter().map(Tree::to_value).collect()),
            Tree::Obj(entries) => Value::Object(entries.iter().map(|(k, v)| (k.clone(), v.to_value())).collect()),
        }
    }
}

/// A JS string value built from Rust text.
pub(crate) fn str_tree(text: &str) -> Tree {
    Tree::Str(text.to_owned())
}

/// JS truthiness of an optional member (`undefined` is falsy).
pub(crate) fn truthy(value: Option<&Tree>) -> bool {
    match value {
        None | Some(Tree::Null) => false,
        Some(Tree::Bool(b)) => *b,
        Some(Tree::Num(n)) => n.as_f64().is_some_and(|f| f != 0.0 && !f.is_nan()),
        Some(Tree::Str(s)) => !s.is_empty(),
        Some(Tree::Arr(_) | Tree::Obj(_)) => true,
    }
}

/// JS `value ?? fallback` input: `undefined` and `null` are nullish.
pub(crate) fn defined(value: Option<&Tree>) -> Option<&Tree> {
    value.filter(|v| **v != Tree::Null)
}

/// JS `a === b` between values parsed from distinct places: two objects or
/// arrays are never identical (they are distinct references after a JSON hop).
pub(crate) fn strict_eq(a: Option<&Tree>, b: Option<&Tree>) -> bool {
    match (a, b) {
        (None, None) | (Some(Tree::Null), Some(Tree::Null)) => true,
        (Some(Tree::Bool(x)), Some(Tree::Bool(y))) => x == y,
        (Some(Tree::Num(x)), Some(Tree::Num(y))) => x.as_f64() == y.as_f64(),
        (Some(Tree::Str(x)), Some(Tree::Str(y))) => x == y,
        _ => false,
    }
}

/// Parses the page's `JSON.stringify` text, keeping key order.
///
/// # Errors
/// The parser message for text that is not JSON.
pub(crate) fn parse(text: &str) -> Result<Tree, String> {
    serde_json::from_str(text).map_err(|e| e.to_string())
}

/// JSON text in the tree's key order (the page `JSON.parse`s it back).
pub(crate) fn to_text(tree: &Tree) -> Result<String, String> {
    serde_json::to_string(tree).map_err(|e| e.to_string())
}

struct TreeVisitor;

impl<'de> Visitor<'de> for TreeVisitor {
    type Value = Tree;
    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("a JSON value")
    }
    fn visit_unit<E>(self) -> Result<Tree, E> {
        Ok(Tree::Null)
    }
    fn visit_none<E>(self) -> Result<Tree, E> {
        Ok(Tree::Null)
    }
    fn visit_bool<E>(self, v: bool) -> Result<Tree, E> {
        Ok(Tree::Bool(v))
    }
    fn visit_i64<E>(self, v: i64) -> Result<Tree, E> {
        Ok(Tree::Num(Number::from(v)))
    }
    fn visit_u64<E>(self, v: u64) -> Result<Tree, E> {
        Ok(Tree::Num(Number::from(v)))
    }
    fn visit_f64<E: serde::de::Error>(self, v: f64) -> Result<Tree, E> {
        Number::from_f64(v).map(Tree::Num).ok_or_else(|| E::custom("non-finite number"))
    }
    fn visit_str<E>(self, v: &str) -> Result<Tree, E> {
        Ok(Tree::Str(v.to_owned()))
    }
    fn visit_string<E>(self, v: String) -> Result<Tree, E> {
        Ok(Tree::Str(v))
    }
    fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Tree, A::Error> {
        let mut items = Vec::new();
        while let Some(item) = seq.next_element()? {
            items.push(item);
        }
        Ok(Tree::Arr(items))
    }
    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Tree, A::Error> {
        // `JSON.parse` keeps the last duplicate at the first one's position.
        let mut tree = Tree::object();
        while let Some((key, value)) = map.next_entry::<String, Tree>()? {
            tree.set(&key, value);
        }
        Ok(tree)
    }
}

impl<'de> Deserialize<'de> for Tree {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Tree, D::Error> {
        deserializer.deserialize_any(TreeVisitor)
    }
}

impl Serialize for Tree {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        match self {
            Tree::Null => serializer.serialize_unit(),
            Tree::Bool(b) => serializer.serialize_bool(*b),
            Tree::Num(n) => n.serialize(serializer),
            Tree::Str(s) => serializer.serialize_str(s),
            Tree::Arr(items) => {
                let mut seq = serializer.serialize_seq(Some(items.len()))?;
                for item in items {
                    seq.serialize_element(item)?;
                }
                seq.end()
            }
            Tree::Obj(entries) => {
                let mut map = serializer.serialize_map(Some(entries.len()))?;
                for (key, value) in entries {
                    map.serialize_entry(key, value)?;
                }
                map.end()
            }
        }
    }
}
