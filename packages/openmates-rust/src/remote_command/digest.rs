//! npm-identical definition digests. Both CLIs must produce the same hex so a
//! grant enabled by either one authorizes the same definition.
use super::permissions::RemoteCommandPermissions;
use super::{RemoteCommandError, RemoteCommandResult as R};
use icu_collator::{Collator, CollatorBorrowed, options::CollatorOptions};
use serde::Serialize;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;

fn sha256_hex(value: &str) -> String {
    format!("{:x}", Sha256::digest(value.as_bytes()))
}

/// npm `stableJson`: arrays in order, object keys sorted with
/// `String.prototype.localeCompare` (default ICU collation; the pinned en-US
/// root collator here), scalars via `JSON.stringify` escaping, which
/// `serde_json` matches for every value a Rust `String` can hold.
pub fn stable_json(value: &Value) -> R<String> {
    let locale: icu_locale_core::Locale = "en-US"
        .parse()
        .map_err(|_| RemoteCommandError::failed("Collation locale is unavailable."))?;
    let collator = Collator::try_new(locale.into(), CollatorOptions::default())
        .map_err(|_| RemoteCommandError::failed("Collation data is unavailable."))?;
    let mut out = String::new();
    write_stable(value, &collator, &mut out);
    Ok(out)
}
fn write_stable(value: &Value, collator: &CollatorBorrowed<'static>, out: &mut String) {
    match value {
        Value::Array(items) => {
            out.push('[');
            for (index, item) in items.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                write_stable(item, collator, out);
            }
            out.push(']');
        }
        Value::Object(map) => {
            let mut entries = map.iter().collect::<Vec<_>>();
            // Stable sort, like Array.prototype.sort.
            entries.sort_by(|(left, _), (right, _)| collator.compare(left, right));
            out.push('{');
            for (index, (key, item)) in entries.into_iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                out.push_str(&Value::String(key.clone()).to_string());
                out.push(':');
                write_stable(item, collator, out);
            }
            out.push('}');
        }
        scalar => out.push_str(&scalar.to_string()),
    }
}

/// npm `remoteCommandPresetDigest`: SHA-256 over the stable JSON of the preset
/// plus only the resource profiles its commands reference, in file order.
pub fn remote_command_preset_digest(
    config: &RemoteCommandPermissions,
    preset_id: &str,
) -> R<String> {
    let preset = config
        .presets
        .iter()
        .find(|candidate| candidate.id == preset_id)
        .ok_or_else(|| {
            RemoteCommandError::failed(format!("Unknown command preset: {preset_id}"))
        })?;
    let writable = preset
        .commands
        .iter()
        .flat_map(|command| command.writable_profiles.iter().map(String::as_str))
        .collect::<BTreeSet<_>>();
    let network = preset
        .commands
        .iter()
        .filter_map(|command| command.network_profile.as_deref())
        .collect::<BTreeSet<_>>();
    let credentials = preset
        .commands
        .iter()
        .flat_map(|command| command.credential_profiles.iter().map(String::as_str))
        .collect::<BTreeSet<_>>();
    let resources = &config.resource_profiles;
    let writable = resources
        .writable
        .iter()
        .filter(|profile| writable.contains(profile.id.as_str()))
        .collect::<Vec<_>>();
    let network = resources
        .network
        .iter()
        .filter(|profile| network.contains(profile.id.as_str()))
        .collect::<Vec<_>>();
    let credentials = resources
        .credentials
        .iter()
        .filter(|profile| credentials.contains(profile.id.as_str()))
        .collect::<Vec<_>>();
    let value = json!({
        "preset": preset,
        "resources": {"writable": writable, "network": network, "credentials": credentials},
    });
    Ok(sha256_hex(&stable_json(&value)?))
}

/// npm `definitionDigest`: SHA-256 of
/// `JSON.stringify(["openmates-command-resource-v1", kind, definition])`
/// with the definition's own field order (not sorted).
pub fn resource_definition_digest(kind: &str, definition: &impl Serialize) -> R<String> {
    let text = serde_json::to_string(&("openmates-command-resource-v1", kind, definition))
        .map_err(|_| RemoteCommandError::failed("Resource definition could not be serialized."))?;
    Ok(sha256_hex(&text))
}
