//! Fixed settings-response root ordering; no global Value/transport feature.
use serde::{
    Deserialize, Deserializer, Serialize, Serializer,
    de::{MapAccess, SeqAccess, Visitor},
    ser::SerializeMap,
};
use serde_json::Value;
use std::fmt;
use zeroize::{Zeroize, Zeroizing};
/// Complete settings result plus the root Object.keys order used by the legacy
/// JavaScript API. Nested values retain the existing Value representation.
/// Owned payload and duplicated root-key scratch are wiped on drop/rejection.
pub struct SettingsReadResponse {
    value: Value,
    root_keys: Zeroizing<Vec<String>>,
}
impl SettingsReadResponse {
    pub fn value(&self) -> &Value {
        &self.value
    }
    pub fn root_keys(&self) -> &[String] {
        &self.root_keys
    }
    /// Move the complete ordinary Value out without another parse/request.
    pub fn into_value(mut self) -> Value {
        std::mem::take(&mut self.value)
    }
    pub(crate) fn from_parts(value: Value, root_keys: Zeroizing<Vec<String>>) -> Self {
        Self { value, root_keys }
    }
    pub(crate) fn into_parts(mut self) -> (Value, Zeroizing<Vec<String>>) {
        (
            std::mem::take(&mut self.value),
            std::mem::take(&mut self.root_keys),
        )
    }
    pub(crate) fn decode_legacy(bytes: &[u8]) -> crate::Result<Self> {
        match serde_json::from_slice(bytes) {
            Ok(response) => Ok(response),
            Err(error) if error.is_eof() || known_malformed_syntax(&error, bytes) => Ok(Self::from_parts(
                serde_json::json!({}),
                Zeroizing::new(Vec::new()),
            )),
            // Syntax also includes recursion/numeric/representation limits in
            // the selected serde parser. A valid but unsupported response must
            // never be published as an invented empty success. Unknown parser
            // failures refuse as well; no generic Protocol error is reclassified.
            Err(_) => Err(crate::Error::Unavailable {
                code: "settings_json_unsupported",
                reason: "SETTINGS_RESPONSE_EXCEEDS_SUPPORTED_JSON_LIMITS_OR_REPRESENTATION",
            }),
        }
    }
}
// Public serde error categories group NumberOutOfRange/RecursionLimitExceeded
// with malformed syntax. Match ONLY known malformed diagnostics from the locked
// parser; unknown/new diagnostics fail closed. This scratch is never displayed.
fn known_malformed_syntax(error: &serde_json::Error, bytes: &[u8]) -> bool {
    if !error.is_syntax() {
        return false;
    }
    let diagnostic = Zeroizing::new(error.to_string());
    let message = diagnostic
        .rsplit_once(" at line ")
        .map_or(diagnostic.as_str(), |(message, _)| message);
    // The locked UTF-8 decoder also uses this syntax diagnostic for a valid
    // JSON string containing an unpaired leading UTF-16 surrogate. RawValue's
    // borrowed syntax scanner validates escapes without requiring UTF-8 string
    // representation. Only an actually malformed token gets the legacy empty
    // fallback; a valid unsupported string must retain the typed refusal.
    if message == "unexpected end of hex escape" {
        return serde_json::from_slice::<&serde_json::value::RawValue>(bytes).is_err();
    }
    matches!(
        message,
        "expected `:`"
            | "expected `,` or `]`"
            | "expected `,` or `}`"
            | "expected ident"
            | "expected value"
            | "expected `\"`"
            | "invalid escape"
            | "invalid number"
            | "control character (\\u0000-\\u001F) found while parsing a string"
            | "key must be a string"
            | "trailing comma"
            | "trailing characters"
    )
}
impl SettingsReadResponse {
    fn wipe(&mut self) {
        crate::model::zeroize_json(&mut self.value);
        self.root_keys.zeroize();
    }
}
impl Drop for SettingsReadResponse {
    fn drop(&mut self) {
        self.wipe();
    }
}
fn index(key: &str) -> Option<u32> {
    key.parse::<u32>()
        .ok()
        .filter(|v| *v != u32::MAX && v.to_string() == key)
}
impl Serialize for SettingsReadResponse {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        if let Some(object) = self.value.as_object() {
            let mut map = serializer.serialize_map(Some(object.len()))?;
            for key in self.root_keys.iter() {
                let value = object
                    .get(key)
                    .ok_or_else(|| serde::ser::Error::custom("invalid settings response order"))?;
                map.serialize_entry(key, value)?;
            }
            map.end()
        } else {
            self.value.serialize(serializer)
        }
    }
}
struct RootVisitor;
impl<'de> Visitor<'de> for RootVisitor {
    type Value = SettingsReadResponse;
    fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("a settings JSON value")
    }
    fn visit_map<M: MapAccess<'de>>(self, mut map: M) -> Result<Self::Value, M::Error> {
        let mut response = SettingsReadResponse::from_parts(
            Value::Object(serde_json::Map::new()),
            Zeroizing::new(Vec::new()),
        );
        while let Some(key) = map.next_key::<String>()? {
            let key = Zeroizing::new(key);
            let value = map.next_value::<Value>()?;
            let object = response.value.as_object_mut().expect("root object");
            if let Some(replaced) = object.get_mut(key.as_str()) {
                crate::model::zeroize_json(replaced);
                *replaced = value;
            } else {
                response.root_keys.push(key.to_string());
                object.insert(key.to_string(), value);
            }
        }
        // Object.keys: canonical array-index names precede other names; stable
        // sorting retains first occurrence of duplicate/non-index properties.
        response
            .root_keys
            .sort_by(|a, b| match (index(a), index(b)) {
                (Some(a), Some(b)) => a.cmp(&b),
                (Some(_), None) => std::cmp::Ordering::Less,
                (None, Some(_)) => std::cmp::Ordering::Greater,
                (None, None) => std::cmp::Ordering::Equal,
            });
        Ok(response)
    }
    fn visit_seq<S: SeqAccess<'de>>(self, mut seq: S) -> Result<Self::Value, S::Error> {
        let mut response =
            SettingsReadResponse::from_parts(Value::Array(Vec::new()), Zeroizing::new(Vec::new()));
        while let Some(value) = seq.next_element::<Value>()? {
            response
                .value
                .as_array_mut()
                .expect("root array")
                .push(value);
        }
        Ok(response)
    }
    fn visit_bool<E: serde::de::Error>(self, v: bool) -> Result<Self::Value, E> {
        Ok(SettingsReadResponse::from_parts(
            Value::Bool(v),
            Zeroizing::new(Vec::new()),
        ))
    }
    fn visit_i64<E: serde::de::Error>(self, v: i64) -> Result<Self::Value, E> {
        Ok(SettingsReadResponse::from_parts(
            Value::from(v),
            Zeroizing::new(Vec::new()),
        ))
    }
    fn visit_u64<E: serde::de::Error>(self, v: u64) -> Result<Self::Value, E> {
        Ok(SettingsReadResponse::from_parts(
            Value::from(v),
            Zeroizing::new(Vec::new()),
        ))
    }
    fn visit_f64<E: serde::de::Error>(self, v: f64) -> Result<Self::Value, E> {
        Ok(SettingsReadResponse::from_parts(
            Value::from(v),
            Zeroizing::new(Vec::new()),
        ))
    }
    fn visit_str<E: serde::de::Error>(self, v: &str) -> Result<Self::Value, E> {
        self.visit_string(v.into())
    }
    fn visit_string<E: serde::de::Error>(self, v: String) -> Result<Self::Value, E> {
        Ok(SettingsReadResponse::from_parts(
            Value::String(v),
            Zeroizing::new(Vec::new()),
        ))
    }
    fn visit_unit<E: serde::de::Error>(self) -> Result<Self::Value, E> {
        Ok(SettingsReadResponse::from_parts(
            Value::Null,
            Zeroizing::new(Vec::new()),
        ))
    }
}
impl<'de> Deserialize<'de> for SettingsReadResponse {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        deserializer.deserialize_any(RootVisitor)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn fixed_decode_retains_real_root_order_separate_from_value_equality() {
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/sdk-conformance/fixtures/session-settings-reminders-read.json");
        let fixture: Value = serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
        let previous = fixture["cases"].as_array().unwrap();
        assert_eq!(previous.len(), 28);
        for case in previous.iter().skip(23).take(3) {
            let decoded = SettingsReadResponse::decode_legacy(
                case["responses"][0]["body"].as_str().unwrap().as_bytes(),
            )
            .unwrap();
            assert_eq!(decoded.value(), &case["expected"]["value"]);
            assert_eq!(
                serde_json::json!(decoded.root_keys()),
                case["expected"]["root_keys"]
            );
            assert_eq!(
                serde_json::to_string(&decoded).unwrap(),
                case["expected"]["serialized_json"].as_str().unwrap()
            );
            assert_eq!(decoded.into_value(), case["expected"]["value"]);
        }
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,sdk.encryption.local-only
    #[test]
    fn malformed_partial_object_defaults_to_empty_and_owned_payload_and_keys_wipe() {
        for bytes in [
            b"{\"private-field\":\"private-value\",\"broken\":".as_slice(),
            b"{\"z\":1} trailing",
            b"",
            br#""\u12""#,
            br#""\ud800\q""#,
        ] {
            let decoded = SettingsReadResponse::decode_legacy(bytes).unwrap();
            assert_eq!(decoded.value(), &serde_json::json!({}));
            assert!(decoded.root_keys().is_empty());
        }
        let mut decoded =
            SettingsReadResponse::decode_legacy(br#"{"private-field":"private-value"}"#).unwrap();
        assert_eq!(decoded.root_keys(), ["private-field"]);
        decoded.wipe();
        assert!(decoded.value().is_null());
        assert!(decoded.root_keys().is_empty());
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity
    #[test]
    fn convenience_keeps_complete_non_object_values_and_empty_object_fallback() {
        for bytes in [
            b"null".as_slice(),
            b"[1,false,\"opaque\"]",
            b"17",
            b"\"text\"",
            b"true",
            b"1.5",
        ] {
            let expected: Value = serde_json::from_slice(bytes).unwrap();
            let decoded = SettingsReadResponse::decode_legacy(bytes).unwrap();
            assert!(decoded.root_keys().is_empty());
            assert_eq!(decoded.value(), &expected);
            assert_eq!(
                serde_json::from_str::<Value>(&serde_json::to_string(&decoded).unwrap()).unwrap(),
                expected
            );
        }
    }
}

#[cfg(test)]
mod unsupported_tests {
    use super::*;
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn supported_limits_never_fabricate_empty_success_from_valid_unsupported_json() {
        let deep = format!("{{\"extension\":{}0{}}}", "[".repeat(129), "]".repeat(129));
        for bytes in [
            deep.as_bytes(),
            b"1e400",
            br#""\ud800""#,
            br#""\udc00""#,
            br#"{"extension":"\ud800"}"#,
            br#"["\ud800"]"#,
        ] {
            match SettingsReadResponse::decode_legacy(bytes) {
                Err(crate::Error::Unavailable { code, reason }) => {
                    assert_eq!(code, "settings_json_unsupported");
                    assert_eq!(
                        reason,
                        "SETTINGS_RESPONSE_EXCEEDS_SUPPORTED_JSON_LIMITS_OR_REPRESENTATION"
                    );
                }
                _ => panic!("unsupported JSON must refuse, never become empty success"),
            }
        }
    }
}
