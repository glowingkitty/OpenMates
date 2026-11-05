//! Stateless privacy operations use the shared SDK; no credentials or IO.
use crate::BindingError;
use openmates_sdk::{
    Error,
    privacy::{self, PrivacyOptions},
};
use serde::Deserialize;
use serde_json::{Value, json};

#[derive(Deserialize)]
#[serde(tag = "operation", rename_all = "snake_case", deny_unknown_fields)]
enum Input {
    Prepare {
        text: String,
        memories: Vec<Value>,
        existing_mappings: Vec<Value>,
        enhanced: bool,
    },
    Restore {
        text: String,
        mappings: Vec<Value>,
    },
}

/// Strict foreign transport boundary (16 MiB wire bytes). The SDK separately
/// computes its 4 MiB canonical budget, independent of host number spellings.
pub fn privacy_json(encoded: String) -> Result<String, BindingError> {
    let encoded = zeroize::Zeroizing::new(encoded);
    if encoded.len() > 16 * 1024 * 1024 {
        return Err(Error::Invalid("Privacy input exceeds the supported limit.").into());
    }
    let input: Input = serde_json::from_str(&encoded)
        .map_err(|_| Error::Invalid("Invalid typed privacy input."))?;
    let output = match input {
        Input::Prepare {
            text,
            memories,
            existing_mappings,
            enhanced,
        } => {
            let prepared = privacy::prepare_local(
                &text,
                &memories,
                &existing_mappings,
                &PrivacyOptions { enhanced },
            )?;
            json!({"text":prepared.text,"mappings":prepared.mappings})
        }
        Input::Restore { text, mappings } => {
            json!({"text":privacy::restore_local(&text, &mappings)?})
        }
    };
    serde_json::to_string(&output).map_err(|_| Error::Protocol.into())
}

#[cfg(test)]
mod tests {
    use super::*;
    // contract-test: supporting surface=sdks.rust assertions=pii.surface.semantic-parity
    #[test]
    fn rejects_malformed_unknown_and_bounded_input_without_echoing_secrets() {
        for input in [
            json!({"operation":"prepare","text":"synthetic-secret","memories":[],"existing_mappings":[],"enhanced":false,"unknown":true}),
            json!({"operation":"restore","text":false,"mappings":[]}),
            json!({"operation":"prepare","text":"x","memories":[],"existing_mappings":[],"enhanced":"false"}),
            json!({"operation":"restore","text":"x","mappings":vec![Value::Null;1_025]}),
        ] {
            let error = privacy_json(input.to_string()).err().unwrap();
            assert_eq!(error.code, "invalid_argument");
            assert!(!error.message.contains("synthetic-secret"));
        }
    }
}
