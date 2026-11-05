//! Async key primitives preserve the existing wrapper/Direct selection policy.
//! A capability is an actual native key or opaque platform key resource, never
//! placeholder Session bytes. These helpers cannot mint an auth or read proof.
//! Every platform crypto await remains restricted by credential, key-resource,
//! owner-context, generation and cancellation checks before returning plaintext.
//! Native synchronous APIs remain available with their existing raw-key limits.
use super::plaintext::Plain;
use super::*;
use crate::crypto::master::MasterCapability;
#[path="prepared_chat_key.rs"]
mod prepared_chat_key;
pub(super) use prepared_chat_key::{PreparedChatKey,CompletedChatKey};

pub(super) struct AsyncCryptoScope {
    binding: credentials::MasterBinding,
    authority: std::sync::Arc<project_task_watch::WatchAuthority>,
    generation: u64,
    credential_context: String,
    denial_revision: u64,
    expires_at: Option<u64>,
    operation: CancellationToken,
    original_parent:CancellationToken,
    owned:Option<super::owned_operation::OwnedOperationLease>,
    owned_credential:Option<(u64,zeroize::Zeroizing<[u8;32]>)>,
    owner_context: String,
    team: Option<String>,
}
/// Restrictive observer of original resources only. It cannot decrypt, read,
/// authorize effects, renew identity, or turn a replacement resource into proof.
#[derive(Clone)]
pub(super) struct NegativeCryptoScope {
    browser_master: Option<MasterCapability>,
    authority: std::sync::Arc<project_task_watch::WatchAuthority>,
    denial_revision: u64,
    expires_at: Option<u64>,
}
impl NegativeCryptoScope {
    pub(super) async fn cancelled(&self){
        let master=async{if let Some(master)=&self.browser_master{master.cancelled().await}else{std::future::pending::<()>().await}};
        let expiry=async{if let Some(at)=self.expires_at{loop{let remaining=at.saturating_sub(now_ms());if remaining==0{break}crate::platform::time::sleep(Duration::from_millis(remaining)).await;}}else{std::future::pending::<()>().await}};
        tokio::select!{biased;
            _=self.authority.cancel.cancelled()=>{},
            _=self.authority.cached_denial_changed(self.denial_revision)=>{},
            _=master=>{},_=expiry=>{},
        }
    }

    pub(super) fn check_release(&self) -> Result<()> {
        if let Some(master) = &self.browser_master { master.ensure_current()?; }
        if self.authority.cancel.is_cancelled()
            || self.authority.try_cached_denial_revision()? != self.denial_revision
            || self.expires_at.is_some_and(|at| at <= now_ms()) { return Err(Error::Cancelled); }
        Ok(())
    }
}
fn owner_context(client: &Client) -> Result<String> {
    Ok(sha256(&serde_json::to_string(&(
        &client.user["id"],
        &client.user["user_id"],
        &client.user["username"],
    ))?))
}
fn credential_context(client: &Client) -> Result<String> {
    let scope = client.require_credentials()?;
    Ok(sha256(&serde_json::to_string(&(
        scope.api_url,
        scope.session_id,
        scope.hashed_email,
        scope.active_team_id,
    ))?))
}
impl AsyncCryptoScope {
    /// Observe only revocation of the actual captured opaque master resource.
    /// No Client, raw key export, ownership, read or effect authority is added.
    pub(super) fn ensure_resource_current(&self) -> Result<()> {
        self.binding.ensure_resource_current()
    }
    pub(super) fn begin(client: &Client) -> Result<Self> {
        client.require_credentials()?;
        let owned=client.active_owned_operation.clone();
        if let Some(lease)=&owned{lease.check_initial_credentials(client,false)?;}
        let owned_credential=if owned.is_some(){Some((client.credential_revision,zeroize::Zeroizing::new(client.owned_operations.checked_auth_binding(client)?)))}else{None};
        let scope = Self {
            binding: client.master_binding()?,
            authority: client.task_watch_authority.clone(),
            generation: client.generation,
            credential_context: credential_context(client)?,
            denial_revision: client.task_watch_authority.cached_denial_revision()?,
            expires_at: client.require_credentials()?.paired_session_expires_at,
            operation: client.current_operation_child(),
            original_parent:client.operation_parent.clone(),
            owned,owned_credential,
            owner_context: owner_context(client)?,
            team: client.team()?.map(str::to_owned),
        };
        scope.check(client)?;
        Ok(scope)
    }
    /// Promote only this already validated original scope to its exact issued
    /// sibling. No caller child/token/current status can construct that identity.
    pub(super) fn into_owned(mut self,client:&Client,lease:super::owned_operation::OwnedOperationLease)->Result<Self>{
        self.check(client)?;lease.check_initial_credentials(client,false)?;
        self.operation=lease.child().clone();self.owned=Some(lease);
        self.owned_credential=Some((client.credential_revision,zeroize::Zeroizing::new(client.owned_operations.checked_auth_binding(client)?)));
        self.check(client)?;Ok(self)
    }
    /// Restrictive ORIGINAL operation observation only, with no Client borrow,
    /// caller callback, auth/read/effect/publication grant or identity refresh.
    /// Call after any captured caller gate; full actual Client checks remain
    /// mandatory around header apply, row/CAS work and final publication.
    pub(super) async fn original_operation_cancelled(&self){
        let owned=async{if let Some(owned)=&self.owned{owned.cancelled().await}else{std::future::pending::<()>().await}};
        let resources=self.negative_observer();
        tokio::select!{biased;_=self.original_parent.cancelled()=>{},_=self.operation.cancelled()=>{},_=owned=>{},_=resources.cancelled()=>{}}
    }
    pub(super) fn check_original_operation_negative(&self)->Result<()> {
        let tokens=||->Result<()> {
            if self.original_parent.is_cancelled()||self.operation.is_cancelled(){return Err(Error::Cancelled)}
            if let Some(owned)=&self.owned {owned.check_original_negative()?;}
            Ok(())
        };
        tokens()?;
        self.negative_observer().check_release()?;
        // Original resource callbacks cannot hide synchronous token revocation.
        tokens()
    }
    pub(super) fn negative_observer(&self) -> NegativeCryptoScope {
        NegativeCryptoScope {
            browser_master: match &self.binding {
                credentials::MasterBinding::Native(_) => None,
                credentials::MasterBinding::Browser(master) => Some(master.clone()),
            },
            authority: self.authority.clone(), denial_revision: self.denial_revision,
            expires_at: self.expires_at,
        }
    }
    pub(super) fn check(&self, client: &Client) -> Result<()> {
        self.check_original_context(client, &self.operation, false)
    }
    /// Negative terminal-lifetime validation only. The one-use scoped-send
    /// driver must already prove its exact child/parent/epoch and termination.
    /// This never releases plaintext or grants read/write/publication authority.
    pub(super) fn check_terminated_child_context(&self, client: &Client) -> Result<()> {
        self.check_original_context(client, &self.operation, true)
    }
    /// Dispatched auth-control-plane observation only. Ignore child/request stop
    /// while retaining original parent, registry, key, owner/team, denial, TTL
    /// and witnessed lineage. This proves neither termination nor continuation.
    pub(super) fn check_dispatched_credential_observation(&self,client:&Client)->Result<()>{
        self.check_original_context(client,&self.operation,true)
    }
    /// Only a consumed scoped-send terminal may attest this exact owned child
    /// transition. Every original identity/denial/resource condition is retained.
    pub(super) fn check_owned_child_transition(&self, client: &Client, child: &CancellationToken) -> Result<()> {
        self.check_original_context(client, child, false)
    }
    fn check_original_context(&self, client: &Client, child: &CancellationToken, terminated_child: bool) -> Result<()> {
        client.require_credentials()?;
        self.binding.check(client)?;
        let original_child=match &self.owned {
            None=>*child==client.operation_cancel,
            Some(owned)=>{
                owned.check_client(client,terminated_child)?;
                let(revision,binding)=self.owned_credential.as_ref().ok_or(Error::Cancelled)?;
                owned.check_credentials(client,*revision,binding,terminated_child)?;
                *child==self.operation && *child==*owned.child()
            }
        };
        if (!terminated_child && (child.is_cancelled() || self.owned.is_none()&&client.operation_cancel.is_cancelled()))
            || self.authority.cancel.is_cancelled()
            || !original_child
            || !std::sync::Arc::ptr_eq(&self.authority, &client.task_watch_authority)
            || self.generation != client.generation
            || self.credential_context != credential_context(client)?
            || self.denial_revision != client.task_watch_authority.cached_denial_revision()?
            || self.expires_at.is_some_and(|value| value <= now_ms())
            || self.owner_context != owner_context(client)?
            || self.team.as_deref() != client.team()?
        {
            return Err(Error::Cancelled);
        }
        Ok(())
    }
    pub(super) fn check_chat(&self, client: &Client, id: &str) -> Result<()> {
        self.check(client)?;
        if !client.task_watch_authority.cached_chat_allowed(id) {
            return Err(Error::Forbidden);
        }
        Ok(())
    }
}
impl Client {
    /// Untagged canonical DTOs require the existing online credential mode.
    /// Local-profile data is available only through the explicit tagged helpers;
    /// this restriction grants no server authority or additional freshness.
    pub(super) fn require_canonical_read_profile(&self) -> Result<()> {
        self.require_credentials()?;
        if self.is_local_browser_profile() {
            return Err(Error::Unavailable {
                code: "local_profile_read_only",
                reason: "Use an explicitly tagged local-profile read.",
            });
        }
        Ok(())
    }
    /// Preserve the common optional ciphertext semantics for an actual master
    /// capability. This primitive grants neither canonical nor local view mode.
    pub(super) async fn decrypt_optional_with_capability(
        &self,
        row: &Value,
        name: &str,
        key: &MasterCapability,
    ) -> Result<String> {
        let scope = AsyncCryptoScope::begin(self)?;
        let mut plain = zeroize::Zeroizing::new(match row.get(name) {
            None | Some(Value::Null) => String::new(),
            Some(Value::String(ciphertext)) if ciphertext.is_empty() => String::new(),
            Some(Value::String(ciphertext)) => key.decrypt_text(ciphertext).await?,
            _ => return Err(Error::Protocol),
        });
        scope.check(self)?;
        Ok(std::mem::take(&mut *plain))
    }
    pub(super) fn cached_wrapping_capability(&self) -> Result<MasterCapability> {
        let scope = AsyncCryptoScope::begin(self)?;
        let result = self.cached_wrapping_capability_selection()?;
        scope.check(self)?;
        Ok(result)
    }
    // Same selection, guarded by the ACTUAL original sibling rather than an
    // unrelated global operation child. No capture or caller status authority.
    pub(super) fn cached_wrapping_capability_for_owned(&self,original:&super::owned_operation::OwnedOperationScope)->Result<MasterCapability>{
        original.check(self)?;
        let result=self.cached_wrapping_capability_selection()?;
        original.check(self)?;Ok(result)
    }
    fn cached_wrapping_capability_selection(&self)->Result<MasterCapability>{
        Ok(
        if let Some(team) = self.team()? {
            let key = self
                .team_key
                .as_ref()
                .filter(|(id, _)| id == team)
                .map(|(_, key)| key.clone())
                .ok_or(Error::Forbidden)?;
            MasterCapability::from_native(key)
        } else {
            self.master_capability()?
        }
        )
    }
    pub(super) async fn wrapping_capability(&mut self) -> Result<MasterCapability> {
        let scope = AsyncCryptoScope::begin(self)?;
        let Some(team) = self.team()?.map(str::to_owned) else {
            return self.master_capability();
        };
        if let Some((id, key)) = &self.team_key
            && *id == team
        {
            return Ok(MasterCapability::from_native(key.clone()));
        }
        let master = self.master_capability()?;
        let result = self
            .request(Method::GET, &format!("/v1/teams/{}", segment(&team)), None)
            .await?;
        scope.check(self)?;
        let row = result.get("team").ok_or(Error::Protocol)?;
        if text(row, "team_id") != team {
            return Err(Error::Forbidden);
        }
        let encrypted = required(row, "encrypted_team_key")?;
        let bytes = master.decrypt_bytes(encrypted).await?;
        scope.check(self)?;
        let key = key_from_bytes(&bytes)?;
        self.team_wrapped_key = Some((team.clone(), encrypted.to_owned()));
        self.team_key = Some((team, key.clone()));
        Ok(MasterCapability::from_native(key))
    }
    pub(super) async fn chat_key_with_capability(
        &self,
        row: &Value,
        wrapping: &MasterCapability,
    ) -> Result<Key> {
        self.chat_key_with_capability_from(row, wrapping, &self.wrappers)
            .await
    }
    pub(super) async fn chat_key_with_capability_from(
        &self,
        row: &Value,
        wrapping: &MasterCapability,
        wrappers: &[Value],
    ) -> Result<Key> {
        self.prepare_chat_key_with_capability_from(row, wrapping, wrappers)?
            .drive().await.finish(self)
    }
    pub(super) async fn chat_item_with_capability(
        &self,
        row: &Value,
        key: &[u8; 32],
    ) -> Result<Item> {
        if !sync::draft_only(row) || self.team()?.is_some() {
            return self.chat_item(row, key);
        }
        self.draft_item_with_capability(row).await
    }
    pub(super) async fn draft_item_with_capability(&self, row: &Value) -> Result<Item> {
        let scope = AsyncCryptoScope::begin(self)?;
        let id = required(row, "id")?;
        scope.check(self)?;
        let master = self.master_capability()?;
        let preview = match row
            .get("encrypted_draft_preview")
            .filter(|value| !value.is_null())
        {
            None => String::new(),
            Some(Value::String(value)) if value.is_empty() => String::new(),
            Some(Value::String(value)) => master.decrypt_text(value).await?,
            _ => return Err(Error::Protocol),
        };
        let mut preview = zeroize::Zeroizing::new(preview);
        scope.check(self)?;
        Ok(Item {
            id: id.into(),
            title: if preview.is_empty() {
                "Draft".into()
            } else {
                std::mem::take(&mut *preview)
            },
            status: "draft".into(),
            fields: json!({"chat_list_title":null}),
            ..Item::default()
        })
    }
    pub(super) async fn render_chat_inventory_with_capability(&self) -> Result<Vec<Item>> {
        self.require_canonical_read_profile()?;
        let scope = AsyncCryptoScope::begin(self)?;
        let wrapping = self.cached_wrapping_capability()?;
        let mut items = PlainItems(vec![]);
        for row in self.chat_rows_by_recency() {
            let item = if sync::draft_only(row) && self.team()?.is_none() {
                self.draft_item_with_capability(row).await?
            } else {
                match self.chat_key_with_capability(row, &wrapping).await {
                    Ok(key) => self.chat_item(row, &key)?,
                    Err(Error::Forbidden) => Item {
                        id: required(row, "id")?.into(),
                        title: "Locked chat".into(),
                        status: "locked".into(),
                        fields: json!({"chat_list_title":null}),
                        ..Item::default()
                    },
                    Err(error) => return Err(error),
                }
            };
            items.0.push(item);
        }
        scope.check(self)?;
        self.require_canonical_read_profile()?;
        Ok(std::mem::take(&mut items.0))
    }
}

pub(super) struct PlainItems(pub(super) Vec<Item>);
impl Drop for PlainItems {
    fn drop(&mut self) {
        for item in &mut self.0 {
            wipe_item(item);
        }
    }
}
pub(super) fn wipe_item(item: &mut Item) {
    use zeroize::Zeroize;
    // Exhaustive destructuring makes a new Item field require a wipe decision.
    let Item {
        id,
        title,
        description,
        status,
        category,
        fields,
    } = item;
    id.zeroize();
    title.zeroize();
    description.zeroize();
    status.zeroize();
    category.zeroize();
    crate::model::zeroize_json(fields);
}

impl Client {
    pub(super) async fn cached_chats_with_capability(&self) -> Result<Vec<Item>> {
        self.require_canonical_read_profile()?;
        let scope = AsyncCryptoScope::begin(self)?;
        let wrapping = self.cached_wrapping_capability()?;
        let mut items = PlainItems(vec![]);
        for row in self.chat_rows_by_recency() {
            let item = if sync::draft_only(row) && self.team()?.is_none() {
                self.draft_item_with_capability(row).await?
            } else {
                let key = self.chat_key_with_capability(row, &wrapping).await?;
                self.chat_item(row, &key)?
            };
            items.0.push(item);
        }
        scope.check(self)?;
        self.require_canonical_read_profile()?;
        Ok(std::mem::take(&mut items.0))
    }
    pub(super) async fn cached_chat_with_capability(&self, id: &str) -> Result<Chat> {
        self.require_canonical_read_profile()?;
        let scope = AsyncCryptoScope::begin(self)?;
        scope.check_chat(self, id)?;
        if self.browser_credentials.is_none() {
            let mut chat = self.cached_chat(id)?;
            if let Err(error) = scope
                .check_chat(self, id)
                .and_then(|_| self.require_canonical_read_profile())
            {
                crate::client::monitor::cached_view::wipe_chat(&mut chat);
                return Err(error);
            }
            return Ok(chat);
        }
        let wrapping = self.cached_wrapping_capability()?;
        let row = self.chats.get(id).ok_or(Error::Offline)?;
        if sync::draft_only(row) && self.team()?.is_none() {
            let mut item = Plain::new(self.draft_item_with_capability(row).await?);
            scope.check_chat(self, id)?;
            self.require_canonical_read_profile()?;
            return Ok(Chat {
                id: id.into(),
                title: std::mem::take(&mut item.title),
                ..Chat::default()
            });
        }
        let key = self.chat_key_with_capability(row, &wrapping).await?;
        let mut item = Plain::new(self.chat_item(row, &key)?);
        let mut messages = Plain::new(Vec::<Message>::new());
        for raw in self.history.get(id).ok_or(Error::Offline)? {
            let mut message = Plain::new(Message {
                id: ["client_message_id", "message_id", "id"]
                    .into_iter()
                    .map(|field| text(raw, field))
                    .find(|id| !id.is_empty())
                    .ok_or(Error::Protocol)?
                    .into(),
                role: required(raw, "role")?.into(),
                ..Message::default()
            });
            message.content = sync::decrypt_optional(raw, "encrypted_content", &key)?;
            message.sender = sync::decrypt_optional(raw, "encrypted_sender_name", &key)?;
            message.thinking = sync::decrypt_optional(raw, "encrypted_thinking_content", &key)?;
            messages.push(message.into_inner());
        }
        let mut chat = Plain::new(Chat {
            id: id.into(),
            title: std::mem::take(&mut item.title),
            category: std::mem::take(&mut item.category),
            messages: messages.into_inner(),
        });
        let rows = self.history.get(id).map(Vec::as_slice).unwrap_or(&[]);
        if let Err(error) = sync::restore_chat_tokens_from_rows(&mut chat, &key, rows)
            .and_then(|_| scope.check_chat(self, id))
            .and_then(|_| self.require_canonical_read_profile())
        {
            crate::client::monitor::cached_view::wipe_chat(&mut chat);
            return Err(error);
        }
        Ok(chat.into_inner())
    }
}

#[cfg(all(test, not(target_arch = "wasm32")))]
#[path = "sync_capability_tests.rs"]
mod tests;
