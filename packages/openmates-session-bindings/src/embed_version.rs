//! Pure explicit-key local reconstruction. No session, profile, IO or authority.
use crate::BindingError;
use openmates_sdk::Error;
use serde::Deserialize;
use serde_json::Value;
use zeroize::Zeroizing;
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Input {
    rows: Vec<Value>,
    key: Vec<u8>,
}
pub fn reconstruct_embed_version_json(encoded: String) -> Result<String, BindingError> {
    let encoded = Zeroizing::new(encoded);
    if encoded.len() > 64 * 1024 * 1024 {
        return Err(Error::Invalid("Version reconstruction input is too large.").into());
    }
    let mut input: Input = serde_json::from_str(&encoded)
        .map_err(|_| Error::Invalid("Invalid typed version reconstruction input."))?;
    let bytes = Zeroizing::new(std::mem::take(&mut input.key));
    let raw: [u8; 32] = bytes.as_slice().try_into().map_err(|_| Error::Crypto)?;
    let key = Zeroizing::new(raw);
    let mut content = openmates_sdk::sdk_embeds::reconstruct_version_rows(&input.rows, &key)?;
    Ok(std::mem::take(&mut *content))
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn stateless_transport_is_closed_and_sanitizes_bad_inputs() {
        for raw in [
            r#"{"rows":[],"key":"synthetic-secret","owner":"foreign"}"#,
            r#"{"rows":[],"key":[]}"#,
        ] {
            let error = reconstruct_embed_version_json(raw.into())
                .err()
                .unwrap_or_else(|| panic!("bad input accepted"));
            assert!(!error.message.contains("synthetic-secret"));
        }
    }
}
