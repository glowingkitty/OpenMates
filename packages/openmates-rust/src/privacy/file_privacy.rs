//! Reversible Project-file privacy for the core's file-job executor (shared core,
//! used by web and CLI shells). Port of `ProjectFilePrivacy` and
//! `projectFilePrivacyStorage` in `frontend/packages/ui/src/services/`; detection
//! reuses the crate's single detector (`detect.rs`). Mappings live only in RAM
//! (originals are zeroized on drop) and are persisted solely as a chat-key
//! encrypted blob. Spec: specifications/features/pii-protection.
use super::{PiiExclusions, detect, generated_token, is_placeholder, legacy_token, placeholder};
use crate::crypto::{decrypt_combined, encrypt_embed_envelope};
use crate::error::{Error, Result};
use crate::web_composer::embed_refs::embed_reference_byte_ranges;
use serde_json::{Map, Value, json};
use std::collections::{HashMap, HashSet};
use zeroize::{Zeroize, ZeroizeOnDrop, Zeroizing};

/// Maximum mappings (values plus conflicts), same as the web layer.
const MAX_MAPPINGS: usize = 10_000;
/// Maximum plaintext bytes of a persisted blob (2 MiB), same as the web layer.
const MAX_BLOB_BYTES: usize = 2 * 1024 * 1024;
/// Protocol commitments that are never content; kept byte-exact by `redact_value`.
const PROTOCOL_KEYS: [&str; 3] = ["expected_base", "content_hash", "proposal_commitment"];

fn refuse(code: &'static str, reason: &'static str) -> Error {
    Error::Unavailable { code, reason }
}

#[derive(Clone, Zeroize, ZeroizeOnDrop)]
struct Mapping {
    placeholder: String,
    original: String,
    ty: Option<String>,
}

impl Mapping {
    fn to_value(&self) -> Value {
        let mut value = json!({"placeholder": self.placeholder, "original": self.original});
        if let Some(ty) = &self.ty {
            value["type"] = json!(ty);
        }
        value
    }
}

/// Placeholder/original bookkeeping for one Project chat.
///
/// Holds secrets: it deliberately has no `Debug` of its contents and zeroizes
/// every original on drop.
#[derive(Clone)]
pub struct FilePrivacy {
    enabled: bool,
    memories: Vec<Value>,
    values: Vec<Mapping>,
    by_placeholder: HashMap<String, usize>,
    by_original: HashMap<String, usize>,
    ambiguous: HashSet<String>,
    conflicts: Vec<Mapping>,
    custom_tokens: HashSet<String>,
    preserve_mapped_tokens: bool,
}

impl std::fmt::Debug for FilePrivacy {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("FilePrivacy")
            .field("mappings", &self.values.len())
            .finish_non_exhaustive()
    }
}

impl Drop for FilePrivacy {
    fn drop(&mut self) {
        for (mut key, _) in self.by_original.drain() {
            key.zeroize();
        }
    }
}

impl FilePrivacy {
    /// Creates the layer from privacy `memories` (detection settings and
    /// personal-data entries), the `enabled` switch and already known mappings.
    ///
    /// # Errors
    /// `pii_mapping_limit` when the mappings exceed 10,000.
    pub fn new(enabled: bool, memories: Vec<Value>, mappings: &[Value]) -> Result<Self> {
        let custom_tokens = memories
            .iter()
            .filter(|m| m["app_id"] == "privacy" && m["item_type"] == "personal_data_entry")
            .filter_map(|m| m["data"]["replaceWith"].as_str().filter(|s| !s.is_empty()))
            .map(|w| {
                if w.starts_with('[') {
                    w.to_owned()
                } else {
                    format!("[{w}]")
                }
            })
            .collect();
        let mut this = Self {
            enabled,
            memories,
            values: Vec::new(),
            by_placeholder: HashMap::new(),
            by_original: HashMap::new(),
            ambiguous: HashSet::new(),
            conflicts: Vec::new(),
            custom_tokens,
            preserve_mapped_tokens: false,
        };
        this.add_mappings(mappings)?;
        Ok(this)
    }

    /// Treats literal spellings of known tokens as genuine (already prepared
    /// CLI messages) instead of shielding them. Mirrors `preserveMappedTokens`.
    #[must_use]
    pub fn preserve_mapped_tokens(mut self) -> Self {
        self.preserve_mapped_tokens = true;
        self
    }

    fn parse(value: &Value) -> Option<Mapping> {
        let placeholder = value.get("placeholder")?.as_str()?;
        let original = value.get("original")?.as_str().filter(|s| !s.is_empty())?;
        is_placeholder(placeholder).then(|| Mapping {
            placeholder: placeholder.to_owned(),
            original: original.to_owned(),
            ty: value.get("type").and_then(Value::as_str).map(str::to_owned),
        })
    }

    /// Adds mappings; a placeholder that maps to two different originals
    /// becomes ambiguous (restoring it is refused) and both are kept for saving.
    /// Malformed entries are skipped, as in the web layer.
    ///
    /// # Errors
    /// `pii_mapping_limit` when values plus conflicts exceed 10,000.
    pub fn add_mappings(&mut self, mappings: &[Value]) -> Result<()> {
        for mapping in mappings.iter().filter_map(Self::parse) {
            match self.by_placeholder.get(&mapping.placeholder) {
                Some(&index) if self.values[index].original != mapping.original => {
                    self.ambiguous.insert(mapping.placeholder.clone());
                    let known = self.conflicts.iter().any(|c| {
                        c.placeholder == mapping.placeholder && c.original == mapping.original
                    });
                    if !known {
                        self.conflicts.push(mapping);
                    }
                }
                Some(_) => {}
                None => {
                    self.by_placeholder
                        .insert(mapping.placeholder.clone(), self.values.len());
                    self.by_original
                        .entry(mapping.original.clone())
                        .or_insert(self.values.len());
                    self.values.push(mapping);
                }
            }
            if self.values.len() + self.conflicts.len() > MAX_MAPPINGS {
                return Err(refuse("pii_mapping_limit", "Too many privacy mappings."));
            }
        }
        Ok(())
    }

    /// Restores placeholders in one pass: restored originals are never scanned
    /// again for tokens.
    ///
    /// # Errors
    /// `pii_mapping_ambiguous` for a placeholder with conflicting originals;
    /// `pii_mapping_unavailable` for an unknown generated, legacy or
    /// personal-entry token.
    pub fn restore_text(&self, text: &str) -> Result<String> {
        let mut out = String::with_capacity(text.len());
        let mut cursor = 0;
        for (start, end) in placeholder::find(text) {
            out.push_str(&text[cursor..start]);
            let token = &text[start..end];
            if self.ambiguous.contains(token) {
                return Err(refuse(
                    "pii_mapping_ambiguous",
                    "A privacy placeholder has conflicting mappings.",
                ));
            }
            match self.by_placeholder.get(token) {
                Some(&index) => out.push_str(&self.values[index].original),
                None if generated_token(token)
                    || legacy_token(token)
                    || self.custom_tokens.contains(token) =>
                {
                    return Err(refuse(
                        "pii_mapping_unavailable",
                        "A privacy placeholder mapping is unavailable.",
                    ));
                }
                None => out.push_str(token),
            }
            cursor = end;
        }
        out.push_str(&text[cursor..]);
        Ok(out)
    }

    /// Restores the `path`, `query` and `glob` string arguments of a tool call
    /// in place; other members are untouched.
    ///
    /// # Errors
    /// As [`Self::restore_text`].
    pub fn restore_arguments(&self, arguments: &mut Value) -> Result<()> {
        if let Some(object) = arguments.as_object_mut() {
            for key in ["path", "query", "glob"] {
                self.restore_member(object, key)?;
            }
        }
        Ok(())
    }

    fn restore_member(&self, object: &mut Map<String, Value>, key: &str) -> Result<()> {
        if let Some(Value::String(text)) = object.get(key) {
            let restored = self.restore_text(text)?;
            object.insert(key.to_owned(), Value::String(restored));
        }
        Ok(())
    }

    /// Restores `path`, `content` and `patch` of a file mutation in place.
    /// Authority fields (operation id, `expected_base`) are never rewritten;
    /// the caller validates the result against the mutation protocol.
    ///
    /// # Errors
    /// As [`Self::restore_text`]; `pii_multiline_patch_token` when a patch line
    /// restores to text containing a newline (would change hunk line counts).
    pub fn restore_mutation_fields(&self, mutation: &mut Value) -> Result<()> {
        let Some(object) = mutation.as_object_mut() else {
            return Ok(());
        };
        self.restore_member(object, "path")?;
        self.restore_member(object, "content")?;
        if let Some(Value::String(patch)) = object.get("patch") {
            let mut lines = Vec::new();
            for line in patch.split('\n') {
                let restored = self.restore_text(line)?;
                if restored.contains('\n') {
                    return Err(refuse(
                        "pii_multiline_patch_token",
                        "A patch line restores to multiple lines.",
                    ));
                }
                lines.push(restored);
            }
            object.insert("patch".to_owned(), Value::String(lines.join("\n")));
        }
        Ok(())
    }

    /// Returns the existing token for `original` or mints `[OM_PII_<32 HEX>]`.
    fn token(&mut self, original: &str, ty: Option<&str>) -> Result<String> {
        let existing = self
            .by_original
            .get(original)
            .map(|&i| &self.values[i])
            .filter(|m| !self.ambiguous.contains(&m.placeholder))
            .or_else(|| {
                self.values
                    .iter()
                    .find(|m| m.original == original && !self.ambiguous.contains(&m.placeholder))
            });
        if let Some(mapping) = existing {
            return Ok(mapping.placeholder.clone());
        }
        let placeholder = loop {
            let candidate = format!(
                "[OM_PII_{}]",
                uuid::Uuid::new_v4().simple().to_string().to_uppercase()
            );
            if !self.by_placeholder.contains_key(&candidate) {
                break candidate;
            }
        };
        let mut mapping = json!({"placeholder": placeholder, "original": original});
        if let Some(ty) = ty {
            mapping["type"] = json!(ty);
        }
        self.add_mappings(std::slice::from_ref(&mapping))?;
        Ok(placeholder)
    }

    /// Replaces known values, detector matches (when enabled) and shields
    /// colliding token spellings with tokens; CR/LF stay intact.
    ///
    /// # Errors
    /// `pii_mapping_limit` when minting would exceed the mapping limit.
    pub fn redact_text(&mut self, text: &str) -> Result<String> {
        let tokens: Vec<(usize, usize)> = placeholder::find(text).collect();
        let mut ranges: Vec<(usize, usize, Option<String>)> = Vec::new();
        for &(start, end) in &tokens {
            let literal = &text[start..end];
            let mapped = self.by_placeholder.contains_key(literal);
            if !(self.preserve_mapped_tokens && mapped)
                && (mapped || generated_token(literal) || legacy_token(literal))
            {
                ranges.push((start, end, None));
            }
        }
        // Embed refs are ids, not personal data: nothing may cut into them.
        let mut shields = tokens;
        shields.extend(embed_reference_byte_ranges(text));
        let mut taken = super::RangeIndex::default();
        for &(s, e) in &shields {
            taken.insert(s, e);
        }
        for &(s, e, _) in &ranges {
            taken.insert(s, e);
        }
        let mut known: Vec<&Mapping> = self.values.iter().collect();
        known.sort_by_key(|m| std::cmp::Reverse(m.original.encode_utf16().count()));
        for mapping in known {
            for (start, _) in text.match_indices(mapping.original.as_str()) {
                let end = start + mapping.original.len();
                if !taken.overlaps(start, end) {
                    taken.insert(start, end);
                    ranges.push((start, end, mapping.ty.clone()));
                }
            }
        }
        if self.enabled {
            let existing: Vec<(usize, usize)> = ranges.iter().map(|r| (r.0, r.1)).collect();
            let found = detect::detect_ranges(
                text,
                &self.memories,
                &PiiExclusions::default(),
                &shields,
                &existing,
            )?;
            for (start, end, kind) in found {
                ranges.push((start, end, (!kind.is_empty()).then_some(kind)));
            }
        }
        ranges.sort_by_key(|r| r.0);
        let mut out = String::with_capacity(text.len());
        let mut cursor = 0;
        for (start, end, ty) in ranges {
            if start < cursor {
                continue;
            }
            out.push_str(&text[cursor..start]);
            for part in text[start..end].split_inclusive('\n') {
                let (body, newline) = match part.strip_suffix("\r\n") {
                    Some(body) => (body, "\r\n"),
                    None => match part.strip_suffix('\n') {
                        Some(body) => (body, "\n"),
                        None => (part, ""),
                    },
                };
                if !body.is_empty() {
                    out.push_str(&self.token(body, ty.as_deref())?);
                }
                out.push_str(newline);
            }
            cursor = end;
        }
        out.push_str(&text[cursor..]);
        Ok(out)
    }

    /// Redacts every string of a JSON value in place, recursively. The protocol
    /// commitments `expected_base`, `content_hash` and `proposal_commitment`
    /// keep their exact bytes. The caller must persist [`Self::saved_mappings`]
    /// before exposing the result to the server or model.
    ///
    /// # Errors
    /// As [`Self::redact_text`].
    pub fn redact_value(&mut self, value: &mut Value) -> Result<()> {
        match value {
            Value::String(text) => *text = self.redact_text(text)?,
            Value::Array(items) => {
                for item in items {
                    self.redact_value(item)?;
                }
            }
            Value::Object(object) => {
                for (key, child) in object.iter_mut() {
                    if !PROTOCOL_KEYS.contains(&key.as_str()) {
                        self.redact_value(child)?;
                    }
                }
            }
            _ => {}
        }
        Ok(())
    }

    /// All mappings (values, then conflicting duplicates) for persistence.
    pub fn saved_mappings(&self) -> Vec<Value> {
        self.values
            .iter()
            .chain(&self.conflicts)
            .map(Mapping::to_value)
            .collect()
    }
}

/// Seals `{chat_id, project_id, mappings}` in the embed-key envelope that the
/// web `encryptWithEmbedKey`/`decryptWithEmbedKey` read, with the chat key.
///
/// # Errors
/// `pii_mapping_limit` above 2 MiB of plaintext; [`Error::Crypto`] on sealing failure.
pub fn seal_mappings(
    chat_id: &str,
    project_id: &str,
    mappings: &[Value],
    chat_key: &[u8; 32],
) -> Result<String> {
    let plaintext = Zeroizing::new(
        json!({"chat_id": chat_id, "project_id": project_id, "mappings": mappings}).to_string(),
    );
    if plaintext.len() > MAX_BLOB_BYTES {
        return Err(refuse(
            "pii_mapping_limit",
            "Privacy mappings are too large.",
        ));
    }
    encrypt_embed_envelope(&plaintext, chat_key)
}

/// Opens a blob written by [`seal_mappings`] (or the web layer).
///
/// # Errors
/// `pii_mapping_unavailable` when it cannot be decrypted or parsed, or belongs
/// to another chat or project.
pub fn open_mappings(
    chat_id: &str,
    project_id: &str,
    ciphertext: &str,
    chat_key: &[u8; 32],
) -> Result<Vec<Value>> {
    let unavailable = || {
        refuse(
            "pii_mapping_unavailable",
            "Saved privacy mappings are unavailable.",
        )
    };
    let plaintext =
        Zeroizing::new(decrypt_combined(ciphertext, chat_key).map_err(|_| unavailable())?);
    let saved: Value = serde_json::from_str(&plaintext).map_err(|_| unavailable())?;
    if saved["chat_id"] != chat_id || saved["project_id"] != project_id {
        return Err(unavailable());
    }
    saved["mappings"]
        .as_array()
        .cloned()
        .ok_or_else(unavailable)
}
