//! Stateless decrypted presentation models for foreign SDKs (npm WASM entry first).
//! Bindings only marshal: the shared `openmates_sdk::model` serde layout fills
//! defaults and refuses missing required fields, so npm never re-implements the
//! Chat/Message/Item shape. Mirrors Python `openmates.models`; vectors live in
//! `tests/sdk-conformance/fixtures/sdk-models.json`.
use crate::BindingError;
use openmates_sdk::{
    Error,
    model::{Chat, Item, Message, Workspace},
};
use serde::Deserialize;
use serde_json::{Value, json};

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Input {
    Chat { value: Value },
    Message { value: Value },
    Item { value: Value },
    Workspaces,
}

fn normalized<T: serde::de::DeserializeOwned + serde::Serialize>(
    value: Value,
    refusal: &'static str,
) -> Result<Value, BindingError> {
    let parsed: T = serde_json::from_value(value).map_err(|_| Error::Invalid(refusal))?;
    serde_json::to_value(parsed).map_err(|_| Error::Protocol.into())
}

/// Parse one model value into its canonical Rust serde layout, or list workspaces.
///
/// # Errors
/// `invalid_argument` for an unknown kind or a value missing required fields
/// (`id`/`title` for Chat and Item; `id`/`role`/`content` for Message). The
/// refusal message never echoes the caller's value.
pub fn models_json(encoded: String) -> Result<String, BindingError> {
    if encoded.len() > 16 * 1024 * 1024 {
        return Err(Error::Invalid("Model input exceeds the supported limit.").into());
    }
    let input: Input =
        serde_json::from_str(&encoded).map_err(|_| Error::Invalid("Invalid typed model input."))?;
    let output = match input {
        Input::Chat { value } => normalized::<Chat>(value, "Invalid chat model.")?,
        Input::Message { value } => normalized::<Message>(value, "Invalid message model.")?,
        Input::Item { value } => normalized::<Item>(value, "Invalid item model.")?,
        Input::Workspaces => Value::Array(
            Workspace::ALL
                .iter()
                .map(|workspace| {
                    serde_json::to_value(workspace)
                        .map(|id| json!({"id": id, "label": workspace.label()}))
                        .map_err(|_| BindingError::from(Error::Protocol))
                })
                .collect::<Result<_, _>>()?,
        ),
    };
    serde_json::to_string(&output).map_err(|_| Error::Protocol.into())
}

#[cfg(test)]
#[path = "models_tests.rs"]
mod tests;
