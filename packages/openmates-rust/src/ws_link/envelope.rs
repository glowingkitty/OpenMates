//! Inbound frame envelope, for adapters whose socket text already lives in
//! Rust. Browser adapters that hand payload objects to JS handlers parse the
//! frame with `JSON.parse` once and pass only the type to the router.
use serde::Deserialize;
use serde_json::value::RawValue;
use std::borrow::Cow;

/// Where the handler payload of a frame comes from (TypeScript rule).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PayloadSource {
    /// `{"type": t, "payload": p}`: `p` (JSON `null` included).
    Payload,
    /// `{"type": t}` without `payload`, or `{"event": e, ...}`: the whole frame.
    WholeFrame,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum EnvelopeError {
    /// Not JSON, or a JSON object with duplicate envelope keys.
    Parse,
    /// JSON without a string `type` or `event` field (`message_error`).
    UnknownStructure,
}

/// A borrowed view of one inbound frame.
#[derive(Debug)]
pub struct Envelope<'a> {
    pub message_type: Cow<'a, str>,
    pub source: PayloadSource,
    /// Raw JSON of the handler payload.
    pub payload: &'a str,
}

#[derive(Deserialize)]
struct Raw<'a> {
    #[serde(borrow, rename = "type")]
    message_type: Option<&'a RawValue>,
    #[serde(borrow)]
    event: Option<&'a RawValue>,
    /// Present-but-`null` stays `Some`, like `payload !== undefined`.
    #[serde(borrow, default, deserialize_with = "present")]
    payload: Option<&'a RawValue>,
}

fn present<'de, D: serde::Deserializer<'de>>(deserializer: D) -> Result<Option<&'de RawValue>, D::Error> {
    <&'de RawValue as Deserialize<'de>>::deserialize(deserializer).map(Some)
}

fn json_string(raw: Option<&RawValue>) -> Option<Cow<'_, str>> {
    let raw = raw?.get();
    if !raw.starts_with('"') {
        return None;
    }
    serde_json::from_str::<Cow<'_, str>>(raw).ok()
}

impl<'a> Envelope<'a> {
    pub fn parse(text: &'a str) -> Result<Self, EnvelopeError> {
        let trimmed = text.trim();
        if trimmed == "null" {
            // TypeScript reads `.type` of `null` and lands in its parse error path.
            return Err(EnvelopeError::Parse);
        }
        if !trimmed.starts_with('{') {
            // Arrays and scalars parse in TypeScript but have no type.
            return match serde_json::from_str::<serde::de::IgnoredAny>(text) {
                Ok(_) => Err(EnvelopeError::UnknownStructure),
                Err(_) => Err(EnvelopeError::Parse),
            };
        }
        let raw: Raw<'a> = serde_json::from_str(text).map_err(|_| EnvelopeError::Parse)?;
        if let Some(message_type) = json_string(raw.message_type) {
            return Ok(match raw.payload {
                Some(payload) => Envelope { message_type, source: PayloadSource::Payload, payload: payload.get() },
                None => Envelope { message_type, source: PayloadSource::WholeFrame, payload: text.trim() },
            });
        }
        match json_string(raw.event) {
            Some(message_type) => Ok(Envelope { message_type, source: PayloadSource::WholeFrame, payload: text.trim() }),
            None => Err(EnvelopeError::UnknownStructure),
        }
    }

    /// `message` of an `error` frame payload, or the payload when it is a string.
    pub fn error_message(&self) -> Option<Cow<'a, str>> {
        if self.message_type != "error" {
            return None;
        }
        #[derive(Deserialize)]
        struct ErrorPayload<'b> {
            #[serde(borrow)]
            message: Option<&'b RawValue>,
        }
        if self.payload.starts_with('"') {
            return serde_json::from_str::<Cow<'a, str>>(self.payload).ok();
        }
        if !self.payload.starts_with('{') {
            return None;
        }
        let parsed: ErrorPayload<'a> = serde_json::from_str(self.payload).ok()?;
        json_string(parsed.message)
    }
}

/// TypeScript authentication-failure detection for `error` frame messages.
pub fn auth_error_message(message: &str) -> bool {
    const NEEDLES: [&str; 5] = ["authentication failed", "please log in again", "session expired", "invalid token", "unauthorized"];
    if message.is_ascii() {
        // Same answer as Unicode lowering for ASCII text, without allocating.
        let haystack = message.as_bytes();
        return NEEDLES.iter().any(|needle| {
            haystack.windows(needle.len()).any(|window| window.eq_ignore_ascii_case(needle.as_bytes()))
        });
    }
    // Unicode lowering can produce ASCII (KELVIN SIGN -> 'k'), like `toLowerCase`.
    let lowered = message.to_lowercase();
    NEEDLES.iter().any(|needle| lowered.contains(needle))
}
