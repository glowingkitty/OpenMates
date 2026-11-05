//! Selected full-ID Personal Cookie saved embeds. No cache writes, prefix search,
//! raw-key export, SDK-key fallback, Team/Direct scope substitution or CLI activation.
use super::{embed_version::VersionReadScope, plaintext::Plain, *};
use std::collections::HashSet;
use zeroize::Zeroizing;

const MAX_CHAIN: usize = 8;
const MAX_WRAPPERS: usize = 1024;
const MAX_BYTES: usize = 16 * 1024 * 1024;
const MAX_UNRELATED_FRAMES: usize = 32;
#[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
#[path="saved_embed_owned.rs"]
mod owned;
#[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
pub use owned::{PreparedOwnedSavedEmbedRead,OwnedSavedEmbedReadStep,OwnedSavedEmbedReadApply,OwnedSavedEmbedReadReady,OwnedSavedEmbedReadControl,OwnedSavedEmbedReadTerminal};

fn unavailable(reason: &'static str) -> Error {
    Error::Unavailable {
        code: "cookie_saved_embed_scope_unavailable",
        reason,
    }
}
fn canonical(id: &str) -> bool {
    uuid::Uuid::parse_str(id).is_ok_and(|id_value| id_value.hyphenated().to_string() == id)
}
fn hash(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
struct SourceChat {
    canonical_id: Option<String>,
    hash: String,
}
fn source_chat(value: &str) -> Result<SourceChat> {
    if canonical(value) {
        Ok(SourceChat {
            canonical_id: Some(value.to_owned()),
            hash: sha256(value),
        })
    } else if hash(value) {
        Ok(SourceChat {
            canonical_id: None,
            hash: value.to_owned(),
        })
    } else {
        Err(Error::Protocol)
    }
}
fn personal(client: &Client) -> Result<()> {
    client.verify_private_operation()?;
    client.require_canonical_read_profile()?;
    if client.team()?.is_some() {
        return Err(unavailable(
            "PERSONAL_FULL_ID_ONLY_TEAM_AND_DIRECT_NOT_ADMITTED",
        ));
    }
    Ok(())
}

/// Owns plaintext and the selected key under the original request/key/owner/
/// denial/deadline scope. Neither Debug, Clone nor Serialize; drop wipes both.
/// JSON and fragment URLs are explicit guarded zeroizing releases, never durable
/// storage or a new authentication/key-enrollment authority.
pub struct SavedEmbedRead {
    scope: VersionReadScope,
    value: Plain<Value>,
    _key: Key,
    source: SourceChat,
    #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
    native_source:Plain<Value>,
}
struct ReadParts {
    value:Plain<Value>,key:Key,source:SourceChat,
    #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
    native_source:Plain<Value>,
}
#[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
#[path="saved_embed_main_native.rs"]
mod main_native;
impl SavedEmbedRead {
    pub fn check(&self, client: &Client) -> Result<()> {
        personal(client)?;
        self.scope.check(client)?;
        check_cached_source(client, &self.scope, &self.source)
    }
    /// Create a fragment-only share from this exact, freshly owner-admitted
    /// saved read. Callers explicitly supply their Client and SDK options; no
    /// ambient credentials, new requests, metadata mutation or key export.
    /// CLI sync/prefix/option parsing remains a separate unfinished adapter.
    pub fn share_url(
        &self,
        client: &Client,
        expires: i64,
        password: &str,
    ) -> Result<Zeroizing<String>> {
        self.check(client)?;
        let id = required(&self.value, "embed_id")?;
        let blob = Zeroizing::new(Client::sdk_embed_share_blob(
            id, &self._key, expires, password,
        )?);
        self.check(client)?;
        let mut origin = client.base.clone();
        if let Some(suffix) = client
            .base
            .host_str()
            .ok_or(Error::Protocol)?
            .strip_prefix("api.")
        {
            origin
                .set_host(Some(&format!("app.{suffix}")))
                .map_err(|_| Error::Protocol)?;
        }
        origin.set_port(None).map_err(|_| Error::Protocol)?;
        let output = Zeroizing::new(format!(
            "{}/share/embed/{}#key={}",
            origin.origin().ascii_serialization(),
            id,
            blob.as_str()
        ));
        self.check(client)?;
        Ok(output)
    }
    pub fn json(&self, client: &Client) -> Result<Zeroizing<String>> {
        self.check(client)?;
        let output = Zeroizing::new(serde_json::to_string(&*self.value)?);
        self.check(client)?;
        Ok(output)
    }
}
fn direct_like(row: &Value) -> bool {
    (!matches!(row.get("chat_visibility"), None | Some(Value::Null))
        && row["chat_visibility"] != "team")
        || ["participant_user_hashes", "participant_key_envelopes"]
            .iter()
            .any(|name| row.get(*name).is_some_and(|v| !v.is_null()))
}
fn team_marked(row: &Value) -> bool {
    ["hashed_team_id", "team_id"]
        .iter()
        .any(|name| row.get(*name).is_some_and(|v| !v.is_null()))
}
trait SelectedReadChecks {fn check(&self,client:&Client)->Result<()>;fn check_chat(&self,client:&Client,id:&str)->Result<()>;}
impl SelectedReadChecks for VersionReadScope {fn check(&self,client:&Client)->Result<()>{VersionReadScope::check(self,client)}fn check_chat(&self,client:&Client,id:&str)->Result<()>{VersionReadScope::check_chat(self,client,id)}}
#[cfg(all(feature="browser-metadata-prototype",any(target_arch="wasm32",test)))]
impl SelectedReadChecks for super::owned_operation::OwnedOperationScope {fn check(&self,client:&Client)->Result<()>{personal(client)?;super::owned_operation::OwnedOperationScope::check(self,client)}fn check_chat(&self,client:&Client,id:&str)->Result<()>{SelectedReadChecks::check(self,client)?;self.crypto.check_chat(client,id)}}
fn check_cached_source(
    client: &Client,
    scope: &impl SelectedReadChecks,
    source: &SourceChat,
) -> Result<()> {
    // A captured revision fences later denials; it does not reject negatives
    // that already existed when the scope began. Always consult that ledger,
    // even when no source row is retained in client.chats.
    if let Some(id) = &source.canonical_id {
        scope.check_chat(client, id)?;
    }
    if !client
        .task_watch_authority
        .cached_chat_hash_allowed(&source.hash)
    {
        return Err(Error::Forbidden);
    }
    for (id, row) in &client.chats {
        if sha256(id) == source.hash {
            scope.check_chat(client, id)?;
            // Match the backend is_direct_chat fail-closed predicate: unknown
            // visibility and any nonnull participant metadata are Direct-like.
            if direct_like(row) || team_marked(row) {
                return Err(unavailable("TEAM_AND_DIRECT_SAVED_EMBEDS_NOT_ADMITTED"));
            }
        }
    }
    Ok(())
}

/// Validate the exact response and wrappers before either staging or decrypting.
/// The dedicated request socket/server Personal ACL supplies source authority;
/// user_id is checked against the freshly authenticated owner, never inferred
/// from plaintext, a cached row, a wrapper hash or a key that happens to decrypt.
fn admit_row(
    client: &Client,
    scope: &impl SelectedReadChecks,
    row: &Value,
    id: &str,
    source: Option<&SourceChat>,
) -> Result<(SourceChat, Value, Vec<Value>)> {
    scope.check(client)?;
    let owner = client.user["id"]
        .as_str()
        .or_else(|| client.user["user_id"].as_str())
        .filter(|value| canonical(value))
        .ok_or(Error::Authentication)?;
    if row["embed_id"].as_str() != Some(id)
        || row["user_id"].as_str() != Some(owner)
        || row["already_encrypted"] != true
        || row["encryption_mode"] != "client"
        || team_marked(row)
        || direct_like(row)
    {
        return Err(Error::Forbidden);
    }
    if !matches!(row["status"].as_str(), Some("finished" | "error")) {
        return Err(unavailable("TERMINAL_CLIENT_ENCRYPTED_EMBEDS_ONLY"));
    }
    let source_chat = source_chat(required(row, "chat_id")?)?;
    let source_hash = source_chat.hash.clone();
    if source.is_some_and(|source| source.hash != source_hash) {
        return Err(Error::Forbidden);
    }
    check_cached_source(client, scope, &source_chat)?;
    // A truncated key page has no continuation operation in request_embed.
    if row["embed_keys_has_more_after"] != false
        || row
            .get("oversized_embed_key_id")
            .is_some_and(|v| !v.is_null())
    {
        return Err(unavailable("COMPLETE_SELECTED_KEY_WINDOW_REQUIRED"));
    }
    let parent = match row.get("parent_embed_id") {
        None | Some(Value::Null) => None,
        Some(Value::String(value)) if canonical(value) && value != id => Some(value.clone()),
        _ => return Err(Error::Protocol),
    };
    let wrappers = row["embed_keys"]
        .as_array()
        .filter(|v| v.len() <= MAX_WRAPPERS)
        .ok_or(Error::Protocol)?;
    for wrapper in wrappers {
        if wrapper["hashed_embed_id"].as_str() != Some(sha256(id).as_str())
            || wrapper
                .get("hashed_user_id")
                .filter(|v| !v.is_null())
                .is_some_and(|v| v.as_str() != Some(sha256(owner).as_str()))
            || ["hashed_team_id", "hashed_project_id"]
                .iter()
                .any(|name| wrapper.get(*name).is_some_and(|v| !v.is_null()))
        {
            return Err(Error::Forbidden);
        }
        match wrapper["key_type"].as_str() {
            Some("master")
                if wrapper["hashed_user_id"].as_str() == Some(sha256(owner).as_str()) => {}
            Some("chat") if wrapper["hashed_chat_id"].as_str() == Some(source_hash.as_str()) => {}
            _ => return Err(unavailable("PERSONAL_MASTER_OR_SOURCE_CHAT_WRAPPERS_ONLY")),
        }
        required(wrapper, "encrypted_embed_key")?;
        // Only the selected wrapper contributes expiry to the retained scope;
        // the shared key engine calls scope.wrapper when attempting it.
    }
    let encrypted_type = required(row, "type")?;
    let encrypted_content = required(row, "content")?;
    if encrypted_type.len() > MAX_BYTES || encrypted_content.len() > MAX_BYTES {
        return Err(Error::Protocol);
    }
    if row
        .get("encrypted_text_preview")
        .is_some_and(|v| !v.is_null() && !v.is_string())
    {
        return Err(Error::Protocol);
    }
    let mut metadata = serde_json::Map::new();
    for name in [
        "user_id",
        "chat_id",
        "message_id",
        "is_private",
        "is_shared",
        "text_length_chars",
        "createdAt",
        "updatedAt",
        "embed_ids",
        "version_number",
        "file_path",
        "content_hash",
    ] {
        if let Some(value) = row.get(name) {
            if !value.is_null() {
                let valid = match name {
                    "is_private" | "is_shared" => value.is_boolean(),
                    "text_length_chars" | "createdAt" | "updatedAt" | "version_number" => {
                        value.as_u64().is_some_and(|n| n <= 9_007_199_254_740_991)
                    }
                    "embed_ids" => value.as_array().is_some_and(|rows| {
                        rows.len() <= 4096
                            && rows
                                .iter()
                                .all(|v| v.as_str().is_some_and(|s| s.len() <= 256))
                    }),
                    _ => value.as_str().is_some_and(|s| s.len() <= 4096),
                };
                if !valid {
                    return Err(Error::Protocol);
                }
            }
            metadata.insert(name.to_owned(), value.clone());
        }
    }
    Ok((
        source_chat,
        json!({"embed_id":id,"encrypted_type":encrypted_type,
        "encrypted_content":encrypted_content,"encrypted_text_preview":row["encrypted_text_preview"],
        "hashed_chat_id":source_hash,"parent_embed_id":parent,"status":row["status"],"metadata":metadata}),
        wrappers.clone(),
    ))
}

fn decode(row: &Value, id: &str, key: &Key) -> Result<Plain<Value>> {
    let kind = Zeroizing::new(crypto::decrypt_combined(
        required(row, "encrypted_type")?,
        key,
    )?);
    let body = Zeroizing::new(crypto::decrypt_combined(
        required(row, "encrypted_content")?,
        key,
    )?);
    let content = Plain::new(super::toon::decode(&body)?);
    let preview = Zeroizing::new(super::sync::decrypt_optional(
        row,
        "encrypted_text_preview",
        key,
    )?);
    Ok(Plain::new(
        json!({"schema_version":1,"embed_id":id,"type":kind.as_str(),
        "content":content.into_inner(),"text_preview":preview.as_str(),"status":row["status"],
        "source_chat_hash":row["hashed_chat_id"],"parent_embed_id":row["parent_embed_id"],
        "metadata":row["metadata"],"source":"selected_cookie_ws","read_only":true,"cached":false}),
    ))
}

impl Client {
    /// Reusable full canonical-ID reader for explicit native or opaque browser
    /// credentials. Prefix/cache resolution and Team/Direct protocol admission
    /// remain separate prerequisites. No Client embed/key cache is changed.
    pub async fn saved_embed(&mut self, id: &str) -> Result<SavedEmbedRead> {
        if !canonical(id) {
            return Err(Error::Invalid("A canonical full embed ID is required."));
        }
        personal(self)?;
        let scope = VersionReadScope::begin_authoritative(self).await?;
        personal(self)?;
        let mut ws = scope.run_io(self.passive_chat_monitor_socket()).await?;
        scope.check(self)?;
        let result = async {
            let mut staged = Plain::new(BTreeMap::new());
            let mut keys = Plain::new(Vec::new());
            let mut visited = HashSet::new();
            let mut wanted = id.to_owned();
            let mut source: Option<SourceChat> = None;
            let mut bytes = 0usize;
            #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
            let mut native_source=Plain::new(Value::Null);
            loop {
                scope.check(self)?;
                if visited.len() >= MAX_CHAIN || !visited.insert(wanted.clone()) {
                    return Err(Error::Crypto);
                }
                scope
                    .run_io(transport::send(
                        &mut ws,
                        "request_embed",
                        json!({"embed_id":wanted}),
                    ))
                    .await?;
                scope.check(self)?;
                let mut response = None;
                for _ in 0..MAX_UNRELATED_FRAMES {
                    // Dedicated socket: preserve error frames using the existing
                    // raw-event opt-in, with fixed typed errors and no server text.
                    let (event, payload) = scope
                        .run_io(async {
                            let (event, value) = transport::receive_ephemeral(&mut ws).await?;
                            let value = Plain::new(value);
                            if event == "error" {
                                return Err(match value["status"].as_u64() {
                                    Some(401) => Error::Expired,
                                    Some(403 | 404) => Error::Forbidden,
                                    _ => Error::Protocol,
                                });
                            }
                            Ok((event, value))
                        })
                        .await?;
                    scope.check(self)?;
                    bytes = bytes
                        .checked_add(Zeroizing::new(serde_json::to_vec(&*payload)?).len())
                        .ok_or(Error::Protocol)?;
                    if bytes > MAX_BYTES {
                        return Err(Error::Protocol);
                    }
                    if event == "send_embed_data" {
                        // One outstanding request on this socket. An unexpected
                        // ID is a mismatch, never an alias or another source.
                        if payload["embed_id"].as_str() != Some(wanted.as_str()) {
                            return Err(Error::Forbidden);
                        }
                        response = Some(payload);
                        break;
                    }
                }
                let response = response.ok_or(Error::Protocol)?;
                #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
                if wanted==id{*native_source=response.clone();}
                let (row_source, row, wrappers) =
                    admit_row(self, &scope, &response, &wanted, source.as_ref())?;
                source.get_or_insert(row_source);
                let parent = row["parent_embed_id"].as_str().map(str::to_owned);
                staged.insert(wanted.clone(), row);
                keys.extend(wrappers);
                if keys.len() > MAX_WRAPPERS {
                    return Err(Error::Protocol);
                }
                match self
                    .selected_embed_key(id, &scope, &staged, &keys, false)
                    .await
                {
                    Ok(key) => {
                        scope.check(self)?;
                        let value = decode(staged.get(id).ok_or(Error::Protocol)?, id, &key)?;
                        scope.check(self)?;
                        return Ok(ReadParts{value,key,source:source.ok_or(Error::Protocol)?,
                            #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
                            native_source});
                    }
                    Err(Error::Forbidden | Error::Crypto) if parent.is_some() => {}
                    Err(error) => return Err(error),
                }
                wanted = parent.ok_or(Error::Forbidden)?;
            }
        }
        .await;
        let _ = crate::platform::time::timeout(Duration::from_millis(100), ws.close(None)).await;
        // Preserve an authoritative denial before a later scope failure masks it.
        if matches!(&result, Err(Error::Expired | Error::Forbidden)) {
            return Err(result.err().ok_or(Error::Protocol)?);
        }
        scope.check(self)?;
        let ReadParts{value,key,source,
            #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
            native_source}=result?;
        let read = SavedEmbedRead {
            scope,
            value,
            _key: key,
            source,
            #[cfg(all(target_arch="wasm32",feature="browser-metadata-prototype"))]
            native_source,
        };
        read.check(self)?;
        Ok(read)
    }
}
#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "saved_embed_tests.rs"]
mod tests;
