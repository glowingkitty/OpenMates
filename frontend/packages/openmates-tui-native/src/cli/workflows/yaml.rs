//! Deserialize YAML under shared allocation/depth/node budgets before typed validation.
use super::*;
use serde::{
    Deserializer,
    de::{self, DeserializeSeed, MapAccess, SeqAccess, Visitor},
};
use std::{cell::Cell, rc::Rc};
#[derive(Clone)]
struct Seed {
    nodes: Rc<Cell<usize>>,
    bytes: Rc<Cell<usize>>,
    depth: usize,
}
impl Seed {
    fn child(&self) -> Self {
        Self {
            nodes: self.nodes.clone(),
            bytes: self.bytes.clone(),
            depth: self.depth + 1,
        }
    }
    fn bytes<E: de::Error>(&self, count: usize) -> Result<(), E> {
        let left = self
            .bytes
            .get()
            .checked_sub(count)
            .ok_or_else(|| E::custom("Expanded Workflow YAML is too large."))?;
        self.bytes.set(left);
        Ok(())
    }
}
impl<'de> DeserializeSeed<'de> for Seed {
    type Value = Value;
    fn deserialize<D: Deserializer<'de>>(self, deserializer: D) -> Result<Value, D::Error> {
        if self.depth > 64 || self.nodes.get() == 0 {
            return Err(de::Error::custom("Workflow YAML is too complex."));
        }
        self.nodes.set(self.nodes.get() - 1);
        deserializer.deserialize_any(self)
    }
}
impl<'de> Visitor<'de> for Seed {
    type Value = Value;
    fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("a bounded JSON-compatible YAML value")
    }
    fn visit_bool<E: de::Error>(self, value: bool) -> Result<Value, E> {
        Ok(json!(value))
    }
    fn visit_i64<E: de::Error>(self, value: i64) -> Result<Value, E> {
        Ok(json!(value))
    }
    fn visit_u64<E: de::Error>(self, value: u64) -> Result<Value, E> {
        Ok(json!(value))
    }
    fn visit_f64<E: de::Error>(self, value: f64) -> Result<Value, E> {
        serde_json::Number::from_f64(value)
            .map(Value::Number)
            .ok_or_else(|| E::custom("Workflow YAML numbers must be finite."))
    }
    fn visit_str<E: de::Error>(self, value: &str) -> Result<Value, E> {
        self.bytes::<E>(value.len())?;
        Ok(json!(value))
    }
    fn visit_string<E: de::Error>(self, value: String) -> Result<Value, E> {
        self.bytes::<E>(value.len())?;
        Ok(Value::String(value))
    }
    fn visit_unit<E: de::Error>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }
    fn visit_none<E: de::Error>(self) -> Result<Value, E> {
        Ok(Value::Null)
    }
    fn visit_seq<A: SeqAccess<'de>>(self, mut sequence: A) -> Result<Value, A::Error> {
        let mut values = vec![];
        while let Some(value) = sequence.next_element_seed(self.child())? {
            values.push(value)
        }
        Ok(Value::Array(values))
    }
    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> Result<Value, A::Error> {
        let mut values = serde_json::Map::new();
        while let Some(key) = map.next_key::<String>()? {
            self.bytes::<A::Error>(key.len())?;
            if values.contains_key(&key) {
                return Err(de::Error::custom("Duplicate Workflow YAML field."));
            }
            let value = map.next_value_seed(self.child())?;
            values.insert(key, value);
        }
        Ok(Value::Object(values))
    }
}
pub(super) fn parse(source: &str) -> Result<Value, CliError> {
    let mut documents = serde_yaml::Deserializer::from_str(source);
    let document = documents
        .next()
        .ok_or_else(|| CliError::Invalid("Workflow YAML document is empty.".into()))?;
    let seed = Seed {
        nodes: Rc::new(Cell::new(50_000)),
        bytes: Rc::new(Cell::new(openmates_sdk::work::WORKFLOW_FILE_MAX_BYTES)),
        depth: 0,
    };
    let value = seed.deserialize(document).map_err(|_| {
        CliError::Invalid(
            "Workflow YAML is invalid, duplicated, or exceeds complexity limits.".into(),
        )
    })?;
    if documents.next().is_some() {
        return Err(CliError::Invalid("Use one Workflow YAML document.".into()));
    }
    Ok(value)
}
