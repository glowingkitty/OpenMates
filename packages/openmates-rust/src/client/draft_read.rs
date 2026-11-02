//! Owner-fenced Personal draft reads. Passive metadata/version operations never
//! request messages, recovery leases, inference or a phase:all sync.
use super::*;
use crate::sdk_drafts::{DraftRecord, EncryptedDraftRecord};
use zeroize::Zeroize;
use crate::client::plaintext::Plain;

#[path="draft_read_phases.rs"]
mod phases;
pub(in crate::client) use phases::{DraftFallbackPolicy,PreparedDraftFallback,DraftVersionsRead};

struct DraftReadFence {
    generation: u64,
    owner: String,
    session_id: String,
    principal: Option<String>,
    key_binding: credentials::MasterBinding,
}
impl DraftReadFence {
    fn capture(c: &Client) -> Result<Self> {
        c.admit_draft_read()?;
        let session = c.require_credentials()?;
        Ok(Self {
            generation: c.generation,
            owner: session.hashed_email.clone(),
            session_id: session.session_id.clone(),
            principal: draft_principal(&c.user).map(str::to_owned),
            key_binding: c.master_binding()?,
        })
    }
    fn check(&self, c: &Client) -> Result<()> {
        c.admit_draft_read()?;
        self.check_credential_scope(c)
    }
    fn check_credential_scope(&self, c: &Client) -> Result<()> {
        let session = c.require_credentials()?;
        if session.active_team_id.is_some() {
            return Err(Error::Cancelled);
        }
        if c.generation != self.generation
            || session.hashed_email.as_str() != self.owner.as_str()
            || session.session_id.as_str() != self.session_id.as_str()
            || self
                .principal
                .as_deref()
                .is_some_and(|owner| draft_principal(&c.user) != Some(owner))
        {
            return Err(Error::Cancelled);
        }
        self.key_binding.check(c)?;
        Ok(())
    }
}
// HTTP status is request-local metadata from the shared transport seam, never
// authority to switch credentials. Only transport/body IO on no successful
// HTTP rejection can invoke another read protocol with the same Cookie owner.
/// Restricting assertion for a caller's final durable output boundary. This is
/// not authentication or a freshness receipt; no serialization/Clone/Debug.
pub struct DraftReadAdmission {
    fence: DraftReadFence,
}
impl DraftReadAdmission {
    pub fn check(&self, client: &Client) -> Result<()> {
        self.fence.check(client)
    }
    /// Encrypted credential persistence only. Ignores operation cancellation and
    /// inference privacy policy; never use this to release plaintext output.
    pub fn check_credential_scope(&self, client: &Client) -> Result<()> {
        self.fence.check_credential_scope(client)
    }
}
fn draft_network_fallback(error: Error, http_failure_status: Option<u16>) -> bool {
    matches!(error, Error::Offline) && http_failure_status.is_none()
}
fn draft_principal(user: &Value) -> Option<&str> {
    user["id"]
        .as_str()
        .filter(|v| !v.is_empty())
        .or_else(|| user["user_id"].as_str().filter(|v| !v.is_empty()))
}

impl Client {
    pub(in crate::client) fn validate_original_physical_draft_scope(&self,physical:&Value,id:&str)->Result<()> {
        if physical.get("chat_id").filter(|v|!v.is_null()).is_some_and(|v|v.as_str()!=Some(id)){return Err(Error::Forbidden)}
        let mut local=Plain::new(physical.clone());
        if local.get("id").is_none_or(Value::is_null){
            if local["chat_id"].as_str()!=Some(id){return Err(Error::Protocol)}
            local["id"]=json!(id);
        }
        self.validate_draft_row_scope(&local,id)
    }
    // The metadata CAS deliberately does not write draft fields. Preserve the
    // actual physical local draft floor/ciphertext in Client too; applying raw
    // server metadata cannot silently clear a field omitted by that response.
    pub(in crate::client) fn merge_original_physical_draft_cache(&self,original:&super::owned_operation::OwnedOperationScope,id:&str,server:&Value,physical:&Value,previous:Option<&Value>)->Result<Value>{
        original.check(self)?;self.validate_draft_row_scope(server,id)?;self.validate_original_physical_draft_scope(physical,id)?;
        let mut local=Plain::new(physical.clone());local["id"]=json!(id);
        // Server metadata keeps its own recency. This is ONLY draft ciphertext
        // and version/floor cache hydration, not a new timestamp/freshness.
        local.as_object_mut().ok_or(Error::Protocol)?.remove("last_edited_overall_timestamp");
        let floor=cached_draft_floor(&local)?;
        if (local["encrypted_draft_md"].is_null()||local["encrypted_draft_md"].as_str()==Some(""))&&cleared_draft_version(&local)?.is_some(){local["draft_v"]=json!(floor);}
        // Existing version/same-clock cipher mismatch rule: uncertain local
        // divergence refuses rather than discarding unpersisted editor data.
        self.check_draft_regression(previous,&local)?;
        if previous.is_some_and(|row|row["encrypted_draft_md"].is_string())&&local["encrypted_draft_md"].is_null()&&floor==0{return Err(Error::Conflict)}
        let mut merged=merge_draft_fields(Some(server),&local)?;
        if let Some(cleared)=physical.get("cleared_draft_v"){merged["cleared_draft_v"]=cleared.clone();}
        original.check(self)?;Ok(merged)
    }
    pub fn draft_read_admission(&self) -> Result<DraftReadAdmission> {
        Ok(DraftReadAdmission {
            fence: DraftReadFence::capture(self)?,
        })
    }
    fn admit_draft_read(&self) -> Result<()> {
        self.require_credentials()?;
        self.verify_private_operation()?;
        if self.operation_cancel.is_cancelled() {
            return Err(Error::Cancelled);
        }
        if self.team()?.is_some() {
            return Err(Error::Unavailable {
                code: "team_draft_read_unavailable",
                reason: "Team draft reads require explicitly scoped ownership and keys.",
            });
        }
        Ok(())
    }
    /// Existing complete cache admission, with no unrelated Chat decryption.
    pub fn list_cached_drafts(&self) -> Result<Vec<DraftRecord>> {
        let fence = DraftReadFence::capture(self)?;
        if !self.may_read_cached_default_chat_inventory(false)? {
            return Err(Error::Unavailable {
                code: "draft_list_discovery_unavailable",
                reason: "A complete fresh cached Personal draft projection is unavailable.",
            });
        }
        release_drafts(self, &fence, self.render_cached_drafts())
    }
    fn render_cached_drafts(&self) -> Result<Vec<DraftRecord>> {
        self.render_draft_rows(
            self.chats
                .values()
                .filter(|row| row["encrypted_draft_md"].is_string())
                .collect(),
        )
    }

    /// Cold/explicit refresh uses existing metadata-only phase2: recent100 chat
    /// metadata plus the server's persisted/cache draft discovery. This does not
    /// create a complete Chat census or mark unrelated cached history fresh.
    pub async fn list_drafts(&mut self, force_refresh: bool) -> Result<Vec<DraftRecord>> {
        self.admit_draft_read()?;
        if !force_refresh && self.may_read_cached_default_chat_inventory(false)? {
            let fence = DraftReadFence::capture(self)?;
            return release_drafts(self, &fence, self.render_cached_drafts());
        }
        let fence = DraftReadFence::capture(self)?;
        let requested = self.requested_draft_versions(&[])?;
        let mut socket = self.passive_chat_monitor_socket().await?;
        let result = async {
            fence.check(self)?;
            let versions = if force_refresh {
                Some(
                    self.read_draft_versions_on(&mut socket, &requested, &fence)
                        .await?,
                )
            } else {
                None
            };
            let rows = self
                .read_draft_metadata_on(&mut socket, None, &fence)
                .await?;
            fence.check(self)?;
            let floors = match &versions {
                Some((versions, tombstones)) => {
                    observed_draft_floors(&requested, versions, tombstones)
                }
                None => BTreeMap::new(),
            };
            let observed = versions
                .as_ref()
                .map(|(versions, _)| versions)
                .cloned()
                .unwrap_or_default();
            let mut updates = self.prepare_draft_metadata_at(&rows, &floors, &observed)?;
            if let Some((versions, tombstones)) = &versions {
                for (id, deleted) in
                    self.prepare_draft_versions_at(&requested, versions, tombstones, &floors)?
                {
                    if let Some(row) = rows
                        .get(&id)
                        .filter(|row| row["encrypted_draft_md"].is_string())
                    {
                        if draft_version(row)? <= draft_version(&deleted)? {
                            return Err(Error::Conflict);
                        }
                    } else {
                        if let Some(metadata) = updates.get_mut(&id) {
                            metadata["draft_v"] = json!(
                                cached_draft_floor(metadata)?.max(cached_draft_floor(&deleted)?)
                            );
                        } else {
                            updates.insert(id, deleted);
                        }
                    }
                }
            }
            // Decode every selected draft before committing any ciphertext.
            let mut drafts = self.render_draft_rows(
                rows.values()
                    .filter(|row| row["encrypted_draft_md"].is_string())
                    .collect(),
            )?;
            validate_draft_release(self, &fence, &mut drafts)?;
            self.extend_chat_rows_without_arrival(updates);
            Ok(drafts)
        }
        .await;
        close_draft_socket(&mut socket, &self.operation_cancel).await;
        release_drafts(self, &fence, result)
    }
    pub async fn get_draft(
        &mut self,
        id: &str,
        force_refresh: bool,
    ) -> Result<Option<DraftRecord>> {
        self.admit_draft_read()?;
        uuid::Uuid::parse_str(id).map_err(|_| Error::Invalid("Invalid chat ID."))?;
        if self.is_ephemeral_chat(id) {
            return Err(Error::Invalid("Volatile chats do not have saved drafts."));
        }
        if !force_refresh && self.may_read_cached_default_chat_inventory(false)? {
            let fence = DraftReadFence::capture(self)?;
            let result = match self.chats.get(id).filter(|row|row["encrypted_draft_md"].is_string()) {
                Some(row)=>self.decode_draft_row_with_capability(row).await.map(Some),None=>Ok(None),
            };
            return release_draft(self, &fence, result);
        }
        let fence = DraftReadFence::capture(self)?;
        let previous = self.chats.get(id).cloned();
        if let Some(row) = &previous {
            self.validate_draft_row_scope(row, id)?;
        }
        let mut status = None;
        let response = self
            .request_task_headers_observed(
                Method::GET,
                &format!("/v1/drafts/{id}"),
                None,
                None,
                None,
                None,
                &mut status,
            )
            .await;
        let response = match response {
            Err(error) if draft_network_fallback(error, status) => {
                fence.check(self)?;
                if self.chats.get(id) != previous.as_ref() {
                    return Err(Error::Conflict);
                }
                return self.refresh_draft_from_passive_metadata(id, &fence).await;
            }
            Err(error) => return Err(error),
            Ok(response) => response,
        };
        fence.check(self)?;
        if self.chats.get(id) != previous.as_ref() {
            return Err(Error::Conflict);
        }
        let raw = response.get("draft").ok_or(Error::Protocol)?;
        if raw.is_null() {
            if let Some(row) = self.chats.get_mut(id) {
                clear_ciphertext(row)?;
            }
            return Ok(None);
        }
        let row = self.draft_metadata_row(raw, id, previous.as_ref())?;
        self.check_draft_regression(previous.as_ref(), &row)?;
        let draft = self.decode_draft_row_with_capability(&row).await?;
        let draft = release_draft(self, &fence, Ok(Some(draft)))?.ok_or(Error::Protocol)?;
        self.insert_chat_row(id.into(), row);
        Ok(Some(draft))
    }
    /// Network-only fallback: version check, metadata-only targeted phase2,
    /// version check again, on one passive socket with no credential fallback.
    async fn refresh_draft_from_passive_metadata(
        &mut self,
        id: &str,
        fence: &DraftReadFence,
    ) -> Result<Option<DraftRecord>> {
        fence.check(self)?;
        let mut policy=DraftFallbackPolicy::capture(self,id)?;
        let mut socket = self.passive_chat_monitor_socket().await?;
        let result = async {
            let (first, first_tomb) = self
                .read_draft_versions_on(&mut socket, policy.first_requested(), fence)
                .await?;
            if let Some(prepared)=policy.accept_first(self,first,first_tomb)? {
                fence.check(self)?;
                self.extend_chat_rows_without_arrival(prepared.updates.into_inner());
                return Ok(None);
            }
            let rows = self
                .read_draft_metadata_on(&mut socket, Some(id), fence)
                .await?;
            policy.accept_metadata(self,rows)?;
            let (final_versions, final_tomb) = self
                .read_draft_versions_on(&mut socket, policy.final_requested()?, fence)
                .await?;
            fence.check(self)?;
            let prepared=policy.accept_final(self,final_versions,final_tomb)?;
            let draft=match prepared.row.as_ref(){Some(row)=>Some(self.decode_draft_row_with_capability(row).await?),None=>None};
            let draft=release_draft(self,fence,Ok(draft))?;
            self.extend_chat_rows_without_arrival(prepared.updates.into_inner());
            Ok(draft)
        }
        .await;
        close_draft_socket(&mut socket, &self.operation_cancel).await;
        release_draft(self, fence, result)
    }
    pub async fn reconcile_draft_versions(&mut self) -> Result<BTreeMap<String, u64>> {
        self.admit_draft_read()?;
        let requested = self.requested_draft_versions(&[])?;
        if requested.is_empty() {
            return Ok(BTreeMap::new());
        }
        let fence = DraftReadFence::capture(self)?;
        let mut socket = self.passive_chat_monitor_socket().await?;
        let result = self
            .read_draft_versions_on(&mut socket, &requested, &fence)
            .await;
        close_draft_socket(&mut socket, &self.operation_cancel).await;
        let (versions, tombstones) = result?;
        fence.check(self)?;
        self.commit_draft_versions(&requested, &versions, &tombstones)?;
        Ok(versions)
    }
    fn requested_draft_versions(&self, extra: &[&str]) -> Result<Vec<(String, u64)>> {
        let mut requested = BTreeMap::new();
        for (id, row) in &self.chats {
            if row["encrypted_draft_md"].is_string() {
                self.validate_draft_row_scope(row, id)?;
                requested.insert(id.clone(), cached_draft_floor(row)?);
            }
        }
        for id in extra {
            uuid::Uuid::parse_str(id).map_err(|_| Error::Invalid("Invalid chat ID."))?;
            requested.entry((*id).into()).or_insert(
                self.chats
                    .get(*id)
                    .map(cached_draft_floor)
                    .transpose()?
                    .unwrap_or(0),
            );
        }
        Ok(requested.into_iter().collect())
    }
    async fn read_draft_versions_on(
        &self,
        socket: &mut transport::Socket,
        requested: &[(String, u64)],
        fence: &DraftReadFence,
    ) -> Result<(BTreeMap<String, u64>, BTreeMap<String, u64>)> {
        let mut read=phases::DraftVersionsRead::new(requested);
        while let Some(chunk)=read.next_chunk(){
            fence.check(self)?;
            transport::send(socket,"get_draft_versions",json!({"chats":chunk.iter().map(|(id,version)|json!({"chat_id":id,"client_draft_v":version})).collect::<Vec<_>>()})).await?;
            let response=tokio::select!{biased;_=self.operation_cancel.cancelled()=>return Err(Error::Cancelled),result=transport::wait(socket,"draft_versions_response","","")=>result?};
            fence.check(self)?;read.accept(&response)?;
        }
        read.finish()
    }
    async fn read_draft_metadata_on(
        &self,
        socket: &mut transport::Socket,
        target: Option<&str>,
        fence: &DraftReadFence,
    ) -> Result<BTreeMap<String, Value>> {
        fence.check(self)?;
        let epoch = ((uuid::Uuid::new_v4().as_u128() as u64) & ((1u64 << 53) - 1)).max(2);
        let mut payload = json!({"phase":"phase2","context_epoch":epoch,"client_chat_versions":{},"client_chat_ids":[],"client_embed_ids":[]});
        if let Some(id) = target {
            payload["refresh_chat_ids"] = json!([id]);
        }
        transport::send(socket, "phased_sync_request", payload).await?;
        let deadline = crate::platform::time::Instant::now() + Duration::from_secs(90);
        let mut read = DraftMetadataRead::new(epoch);
        while !read.complete {
            let (kind, payload) = tokio::select! {biased;_=self.operation_cancel.cancelled()=>return Err(Error::Cancelled),result=crate::platform::time::timeout_at(deadline,transport::receive(socket))=>result.map_err(|_|Error::Offline)??};
            fence.check(self)?;
            read.accept(&kind, &payload)?;
        }
        if !read.metadata_seen {
            return Err(Error::Protocol);
        }
        for (id, row) in read.rows.iter() {
            if row["encrypted_draft_md"].is_string() {
                self.validate_draft_row_scope(row, id)?;
            }
        }
        Ok(read.rows.into_inner())
    }
    fn prepare_draft_versions(
        &self,
        requested: &[(String, u64)],
        versions: &BTreeMap<String, u64>,
        tombstones: &BTreeMap<String, u64>,
    ) -> Result<BTreeMap<String, Value>> {
        self.prepare_draft_versions_at(requested, versions, tombstones, &BTreeMap::new())
    }
    fn prepare_draft_versions_at(
        &self,
        requested: &[(String, u64)],
        versions: &BTreeMap<String, u64>,
        tombstones: &BTreeMap<String, u64>,
        floors: &BTreeMap<String, u64>,
    ) -> Result<BTreeMap<String, Value>> {
        for (id, old) in requested {
            if self
                .chats
                .get(id)
                .map(cached_draft_floor)
                .transpose()?
                .unwrap_or(0)
                != *old
            {
                return Err(Error::Conflict);
            }
        }
        let mut updates = BTreeMap::new();
        for (id, version) in versions {
            if *version == 0 {
                let previous = self.chats.get(id);
                let floor = previous
                    .map(cached_draft_floor)
                    .transpose()?
                    .unwrap_or(0)
                    .max(floors.get(id).copied().unwrap_or(0))
                    .max(tombstones.get(id).copied().unwrap_or(0));
                if previous.is_none() && floor == 0 {
                    continue;
                }
                let mut row = previous.cloned().unwrap_or_else(|| json!({"id":id}));
                clear_ciphertext(&mut row)?;
                row["draft_v"] = json!(floor);
                row.as_object_mut()
                    .ok_or(Error::Protocol)?
                    .remove("cleared_draft_v");
                updates.insert(id.clone(), row);
            }
        }
        Ok(updates)
    }
    fn commit_draft_versions(
        &mut self,
        requested: &[(String, u64)],
        versions: &BTreeMap<String, u64>,
        tombstones: &BTreeMap<String, u64>,
    ) -> Result<()> {
        let updates = self.prepare_draft_versions(requested, versions, tombstones)?;
        self.extend_chat_rows_without_arrival(updates);
        Ok(())
    }
    fn prepare_draft_metadata(
        &self,
        rows: &BTreeMap<String, Value>,
    ) -> Result<BTreeMap<String, Value>> {
        self.prepare_draft_metadata_at(rows, &BTreeMap::new(), &BTreeMap::new())
    }
    fn prepare_draft_metadata_at(
        &self,
        rows: &BTreeMap<String, Value>,
        floors: &BTreeMap<String, u64>,
        observed: &BTreeMap<String, u64>,
    ) -> Result<BTreeMap<String, Value>> {
        let mut updates = BTreeMap::new();
        for (id, row) in rows {
            if row["encrypted_draft_md"].is_string() {
                self.validate_draft_row_scope(row, id)?;
                self.check_draft_regression(self.chats.get(id), row)?;
                let version = draft_version(row)?;
                if version < floors.get(id).copied().unwrap_or(0)
                    || cleared_draft_version(row)?.is_some_and(|cleared| version <= cleared)
                {
                    return Err(Error::Conflict);
                }
                updates.insert(id.clone(), merge_draft_fields(self.chats.get(id), row)?);
            } else if row["draft_v"].as_u64() == Some(0) {
                self.validate_draft_row_scope(row, id)?;
                let previous = self.chats.get(id);
                let old = previous.map(cached_draft_floor).transpose()?.unwrap_or(0);
                let observed_positive = observed.get(id).copied().filter(|v| *v > 0).unwrap_or(0);
                let known = old.max(floors.get(id).copied().unwrap_or(0));
                let cleared = cleared_draft_version(row)?;
                if cleared.is_some_and(|cleared| {
                    cleared < known
                        || cleared <= observed_positive
                        || (previous.is_some_and(|row| row["encrypted_draft_md"].is_string())
                            && cleared <= old)
                }) {
                    return Err(Error::Conflict);
                }
                if previous.is_none() && known.max(cleared.unwrap_or(0)) == 0 {
                    continue;
                }
                let mut next = merge_draft_fields(previous, row)?;
                clear_ciphertext(&mut next)?;
                next["draft_v"] = json!(known.max(cleared.unwrap_or(0)));
                next.as_object_mut()
                    .ok_or(Error::Protocol)?
                    .remove("cleared_draft_v");
                updates.insert(id.clone(), next);
            }
        }
        Ok(updates)
    }
    fn render_draft_rows(&self, mut rows: Vec<&Value>) -> Result<Vec<DraftRecord>> {
        rows.sort_by(|a, b| {
            b["last_edited_overall_timestamp"]
                .as_f64()
                .unwrap_or(0.0)
                .partial_cmp(&a["last_edited_overall_timestamp"].as_f64().unwrap_or(0.0))
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        let mut drafts = Vec::new();
        for row in rows {
            match self.decode_draft_row(row) {
                Ok(draft) => drafts.push(draft),
                Err(error) => {
                    wipe_drafts(&mut drafts);
                    return Err(error);
                }
            }
        }
        Ok(drafts)
    }
    fn draft_metadata_row(&self, raw: &Value, id: &str, previous: Option<&Value>) -> Result<Value> {
        if !raw.is_object() || raw["chat_id"] != id {
            return Err(Error::Protocol);
        }
        self.validate_draft_row_scope(raw, id)?;
        let mut row = previous.cloned().unwrap_or_else(|| json!({"id":id}));
        for field in ["encrypted_draft_md", "encrypted_draft_preview", "draft_v"] {
            row[field] = raw[field].clone();
        }
        Ok(row)
    }
    fn check_draft_regression(&self, previous: Option<&Value>, row: &Value) -> Result<()> {
        if let Some(previous) = previous {
            let old = cached_draft_floor(previous)?;
            let version = draft_version(row)?;
            if version < old
                || (old > 0
                    && version == old
                    && (row["encrypted_draft_md"] != previous["encrypted_draft_md"]
                        || row["encrypted_draft_preview"] != previous["encrypted_draft_preview"]))
            {
                return Err(Error::Conflict);
            }
        }
        Ok(())
    }
    pub(super) fn validate_draft_row_scope(&self, row: &Value, id: &str) -> Result<()> {
        if !row.is_object()
            || row
                .get("id")
                .or_else(|| row.get("chat_id"))
                .and_then(Value::as_str)
                != Some(id)
        {
            return Err(Error::Protocol);
        }
        for field in ["team_id", "hashed_team_id"] {
            if row.get(field).is_some_and(|v| !v.is_null() && v != "") {
                return Err(Error::Forbidden);
            }
        }
        if row["chat_visibility"] == "direct" {
            return Err(Error::Forbidden);
        }
        let owner = draft_principal(&self.user);
        for field in ["user_id", "owner_id"] {
            if let Some(value) = row.get(field).filter(|v| !v.is_null() && *v != "") {
                if value.as_str() != owner || owner.is_none() {
                    return Err(Error::Forbidden);
                }
            }
        }
        if let Some(value) = row
            .get("hashed_user_id")
            .filter(|v| !v.is_null() && *v != "")
        {
            if owner.is_none_or(|owner| value != &json!(sha256(owner))) {
                return Err(Error::Forbidden);
            }
        }
        Ok(())
    }
    fn decode_draft_row(&self, row: &Value) -> Result<DraftRecord> {
        self.encrypted_draft_record(row)?.decrypt(&self.require_session()?.master_key)
    }
    pub(super) async fn decode_draft_row_with_capability(&self, row: &Value) -> Result<DraftRecord> {
        let record = self.encrypted_draft_record(row)?;
        let scope = sync_capability::AsyncCryptoScope::begin(self)?;
        let master = self.master_capability()?;
        let mut draft = record.decrypt_with_master_capability(&master).await?;
        if let Err(error)=scope.check(self){wipe_draft(&mut draft);return Err(error)}
        Ok(draft)
    }
    fn encrypted_draft_record(&self, row: &Value) -> Result<EncryptedDraftRecord> {
        let id = required(row, "id")?;
        uuid::Uuid::parse_str(id).map_err(|_| Error::Protocol)?;
        self.validate_draft_row_scope(row, id)?;
        if cleared_draft_version(row)?
            .is_some_and(|cleared| draft_version(row).is_ok_and(|version| version <= cleared))
        {
            return Err(Error::Conflict);
        }
        Ok(EncryptedDraftRecord {
            chat_id: id.into(),
            encrypted_draft_md: required(row, "encrypted_draft_md")?.into(),
            encrypted_draft_preview: match row.get("encrypted_draft_preview") {
                None | Some(Value::Null) => None,
                Some(Value::String(v)) => Some(v.clone()),
                _ => return Err(Error::Protocol),
            },
            draft_v: draft_version(row)?,
        })
    }
}
pub(in crate::client) struct DraftMetadataRead {
    epoch: u64,
    rows: Plain<BTreeMap<String, Value>>,
    metadata_seen: bool,
    complete: bool,
}
impl DraftMetadataRead {
    pub(in crate::client) fn new(epoch: u64) -> Self {
        Self {
            epoch,
            rows: Plain::new(BTreeMap::new()),
            metadata_seen: false,
            complete: false,
        }
    }
    pub(in crate::client) fn accept(&mut self, kind: &str, payload: &Value) -> Result<()> {
        if payload["context_epoch"].as_u64() != Some(self.epoch) {
            return Ok(());
        }
        if !payload["team_id"].is_null() && payload["team_id"] != "" {
            return Err(Error::Forbidden);
        }
        if ["messages", "embeds", "embed_keys", "chat_key_wrappers"]
            .iter()
            .any(|field| {
                payload
                    .get(*field)
                    .is_some_and(|v| v.as_array().is_none_or(|v| !v.is_empty()))
            })
        {
            return Err(Error::Protocol);
        }
        match kind {
            "phase_2_last_20_chats_ready" => {
                if self.metadata_seen || payload["phase"] != "phase2" {
                    return Err(Error::Protocol);
                }
                self.metadata_seen = true;
                for wrapper in payload["chats"].as_array().ok_or(Error::Protocol)? {
                    if ["messages", "embeds", "embed_keys", "chat_key_wrappers"]
                        .iter()
                        .any(|field| {
                            wrapper
                                .get(*field)
                                .is_some_and(|v| v.as_array().is_none_or(|v| !v.is_empty()))
                        })
                    {
                        return Err(Error::Protocol);
                    }
                    let row = wrapper
                        .get("chat_details")
                        .filter(|v| v.is_object())
                        .ok_or(Error::Protocol)?;
                    let id = required(row, "id")?;
                    uuid::Uuid::parse_str(id).map_err(|_| Error::Protocol)?;
                    if self.rows.insert(id.into(), row.clone()).is_some() {
                        return Err(Error::Protocol);
                    }
                }
            }
            "phased_sync_complete" => {
                if payload["phase"] != "phase2" || !self.metadata_seen {
                    return Err(Error::Protocol);
                }
                self.complete = true;
            }
            "phase_1_last_chat_ready"
            | "phase_1b_last_chat_messages_ready"
            | "phase_1b_chat_content_ready"
            | "phase_3_chunk_ready" => return Err(Error::Protocol),
            _ => {}
        }
        Ok(())
    }
}
impl DraftMetadataRead {
    pub(in crate::client) fn terminal(&self)->bool{self.complete}
    pub(in crate::client) fn finish(self)->Result<Plain<BTreeMap<String,Value>>>{
        if !self.complete||!self.metadata_seen{return Err(Error::Protocol)}Ok(self.rows)
    }
}
fn wipe_draft(draft: &mut DraftRecord) {
    draft.markdown.zeroize();
    draft.preview.zeroize();
}
fn wipe_drafts(drafts: &mut [DraftRecord]) {
    for draft in drafts {
        wipe_draft(draft);
    }
}
fn validate_draft_release(
    c: &Client,
    fence: &DraftReadFence,
    drafts: &mut [DraftRecord],
) -> Result<()> {
    if let Err(error) = fence.check(c) {
        wipe_drafts(drafts);
        return Err(error);
    }
    Ok(())
}
fn release_drafts(
    c: &Client,
    fence: &DraftReadFence,
    result: Result<Vec<DraftRecord>>,
) -> Result<Vec<DraftRecord>> {
    let mut value = result?;
    validate_draft_release(c, fence, &mut value)?;
    Ok(value)
}
fn release_draft(
    c: &Client,
    fence: &DraftReadFence,
    result: Result<Option<DraftRecord>>,
) -> Result<Option<DraftRecord>> {
    let mut value = result?;
    if let Err(error) = fence.check(c) {
        if let Some(draft) = &mut value {
            wipe_draft(draft);
        }
        return Err(error);
    }
    Ok(value)
}
fn observed_draft_floors(
    requested: &[(String, u64)],
    versions: &BTreeMap<String, u64>,
    tombstones: &BTreeMap<String, u64>,
) -> BTreeMap<String, u64> {
    requested
        .iter()
        .map(|(id, old)| {
            (
                id.clone(),
                (*old)
                    .max(versions.get(id).copied().unwrap_or(0))
                    .max(tombstones.get(id).copied().unwrap_or(0)),
            )
        })
        .collect()
}
fn cached_draft_floor(row: &Value) -> Result<u64> {
    Ok(draft_version(row)?.max(cleared_draft_version(row)?.unwrap_or(0)))
}
fn cleared_draft_version(row: &Value) -> Result<Option<u64>> {
    match row.get("cleared_draft_v") {
        None | Some(Value::Null) => Ok(None),
        Some(value) => value
            .as_u64()
            .filter(|v| *v > 0)
            .map(Some)
            .ok_or(Error::Protocol),
    }
}
async fn close_draft_socket(socket: &mut transport::Socket, cancel: &CancellationToken) {
    tokio::select! {biased;_=cancel.cancelled()=>{},_ = crate::platform::time::timeout(Duration::from_secs(2),socket.close(None))=>{}}
}
fn merge_draft_fields(previous: Option<&Value>, row: &Value) -> Result<Value> {
    let id = required(row, "id")?;
    let mut merged = previous.cloned().unwrap_or_else(|| json!({"id":id}));
    if previous.is_none() {
        for field in [
            "user_id",
            "owner_id",
            "hashed_user_id",
            "team_id",
            "hashed_team_id",
            "chat_visibility",
            "messages_v",
            "title_v",
            "metadata_v",
            "created_at",
            "updated_at",
            "encrypted_title",
            "encrypted_chat_summary",
            "encrypted_category",
            "encrypted_chat_key",
        ] {
            if let Some(value) = row.get(field) {
                merged[field] = value.clone();
            }
        }
    }
    for field in [
        "encrypted_draft_md",
        "encrypted_draft_preview",
        "draft_v",
        "last_edited_overall_timestamp",
    ] {
        if let Some(value) = row.get(field) {
            merged[field] = value.clone();
        }
    }
    Ok(merged)
}
fn draft_version(row: &Value) -> Result<u64> {
    match row.get("draft_v") {
        None | Some(Value::Null) => Ok(0),
        Some(v) => v.as_u64().ok_or(Error::Protocol),
    }
}
fn clear_ciphertext(row: &mut Value) -> Result<()> {
    let row = row.as_object_mut().ok_or(Error::Protocol)?;
    row.remove("encrypted_draft_md");
    row.remove("encrypted_draft_preview");
    Ok(())
}
fn parse_versions(
    response: &Value,
    requested: &[(String, u64)],
    versions: &mut BTreeMap<String, u64>,
    tombstones: &mut BTreeMap<String, u64>,
) -> Result<()> {
    let raw = response
        .get("versions")
        .and_then(Value::as_object)
        .ok_or(Error::Protocol)?;
    let tomb = response
        .get("tombstone_versions")
        .filter(|v| !v.is_null())
        .map(|v| v.as_object().ok_or(Error::Protocol))
        .transpose()?;
    for (id, value) in raw {
        let old = requested
            .iter()
            .find(|(requested, _)| requested == id)
            .map(|(_, old)| *old)
            .ok_or(Error::Protocol)?;
        let value = value.as_u64().ok_or(Error::Protocol)?;
        if value > 0 && value < old {
            return Err(Error::Conflict);
        }
        if versions.insert(id.clone(), value).is_some() {
            return Err(Error::Protocol);
        }
        if let Some(t) = tomb.and_then(|t| t.get(id)) {
            let t = t
                .as_u64()
                .filter(|t| *t > old && value == 0)
                .ok_or(Error::Conflict)?;
            tombstones.insert(id.clone(), t);
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    fn client() -> Client {
        let endpoint = "http://127.0.0.1:9";
        let mut session = super::super::sdk_boundary_tests::session();
        // Credentials are explicit and bound to this synthetic endpoint; the
        // shared boundary fixture deliberately defaults to a different origin.
        session.api_url = endpoint.into();
        let mut c = Client::new(endpoint, Some(session)).unwrap();
        c.user = json!({"id":"synthetic-owner"});
        c
    }
    fn row(id: &str) -> Value {
        json!({"id":id,"draft_v":3,"encrypted_draft_md":crypto::encrypt_combined("Synthetic draft",&[1;32]).unwrap(),"encrypted_draft_preview":null})
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[test]
    fn cache_decoding_uses_account_key_not_saved_chat_wrappers_and_never_persists_plaintext() {
        let mut c = client();
        let id = "11111111-1111-4111-8111-111111111111";
        c.chats.insert(id.into(), row(id));
        let decoded = c.decode_draft_row(&c.chats[id]).unwrap();
        assert_eq!(decoded.markdown, "Synthetic draft");
        assert_eq!(decoded.preview.as_deref(), Some("Synthetic draft"));
        assert!(
            !c.ciphertext_snapshot()
                .to_string()
                .contains("Synthetic draft")
        );
        assert!(c.wrappers.is_empty());
        assert!(c.history.is_empty());
        let mut corrupted = row(id);
        corrupted["encrypted_draft_preview"] = json!("corrupt");
        assert!(c.decode_draft_row(&corrupted).unwrap().preview.is_none());
        corrupted["encrypted_draft_md"] = json!("corrupt");
        assert!(matches!(c.decode_draft_row(&corrupted), Err(Error::Crypto)));
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[test]
    fn owner_team_direct_and_version_guards_do_not_try_other_keys() {
        let c = client();
        let id = "11111111-1111-4111-8111-111111111111";
        for (field, value) in [
            ("user_id", json!("other")),
            ("hashed_user_id", json!("other")),
            ("team_id", json!("team")),
            ("chat_visibility", json!("direct")),
            ("id", json!("different")),
            ("draft_v", json!(-1)),
        ] {
            let mut bad = row(id);
            bad[field] = value;
            assert!(c.decode_draft_row(&bad).is_err());
        }
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[test]
    fn version_batches_are_bounded_missing_is_not_deletion_and_unsolicited_is_rejected() {
        let requested = vec![("a".into(), 3), ("b".into(), 4)];
        let mut versions = BTreeMap::new();
        let mut tombstones = BTreeMap::new();
        parse_versions(
            &json!({"versions":{"a":0},"tombstone_versions":{"a":5},"unavailable_chat_ids":["b"]}),
            &requested,
            &mut versions,
            &mut tombstones,
        )
        .unwrap();
        assert_eq!(versions, BTreeMap::from([("a".into(), 0)]));
        assert_eq!(tombstones["a"], 5);
        assert!(!versions.contains_key("b"));
        for response in [
            json!({"versions":{"foreign":0}}),
            json!({"versions":{"a":2}}),
            json!({"versions":{"a":0},"tombstone_versions":{"a":2}}),
            json!({"versions":{"a":-1}}),
            json!({"versions":[]}),
        ] {
            assert!(
                parse_versions(
                    &response,
                    &requested,
                    &mut BTreeMap::new(),
                    &mut BTreeMap::new()
                )
                .is_err()
            );
        }
        let items = (0..401).collect::<Vec<_>>();
        assert_eq!(
            items.chunks(200).map(<[_]>::len).collect::<Vec<_>>(),
            vec![200, 200, 1]
        );
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[tokio::test]
    async fn empty_sync_no_network_cold_list_explicit_gap_and_missing_credentials_refuse() {
        let mut c = client();
        let before = c.ciphertext_snapshot();
        assert!(c.reconcile_draft_versions().await.unwrap().is_empty());
        assert_eq!(c.ciphertext_snapshot(), before);
        assert!(matches!(
            c.list_cached_drafts(),
            Err(Error::Unavailable {
                code: "draft_list_discovery_unavailable",
                ..
            })
        ));
        let mut anonymous = Client::new("http://127.0.0.1:9", None).unwrap();
        assert!(matches!(
            anonymous
                .get_draft("11111111-1111-4111-8111-111111111111", true)
                .await,
            Err(Error::Authentication)
        ));
        let cancel = CancellationToken::new();
        cancel.cancel();
        c.set_operation_cancel(cancel);
        assert!(matches!(
            c.reconcile_draft_versions().await,
            Err(Error::Cancelled)
        ));
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[tokio::test]
    async fn targeted_cookie_get_uses_one_rest_read_and_keeps_saved_metadata_history() {
        let id = "11111111-1111-4111-8111-111111111111";
        let raw = row(id);
        let (api,peer)=crate::sdk::tests::server(vec![(200,json!({"draft":{"chat_id":id,"encrypted_draft_md":raw["encrypted_draft_md"],"encrypted_draft_preview":null,"draft_v":3}}))]).await;
        let mut session = super::super::sdk_boundary_tests::session();
        session.api_url = api.clone();
        session
            .cookies
            .insert("auth_refresh_token".into(), "synthetic-cookie".into());
        let mut c = Client::new(&api, Some(session)).unwrap();
        c.user = json!({"id":"synthetic-owner"});
        c.chats.insert(
            id.into(),
            json!({"id":id,"encrypted_title":"opaque-title","messages_v":7}),
        );
        c.history.insert(
            id.into(),
            vec![json!({"id":"message","encrypted_content":"opaque-message"})],
        );
        let loaded = c.get_draft(id, true).await.unwrap().unwrap();
        assert_eq!(loaded.markdown, "Synthetic draft");
        assert_eq!(c.chats[id]["encrypted_title"], "opaque-title");
        assert_eq!(c.history[id].len(), 1);
        let requests = peer.await.unwrap();
        assert_eq!(requests.len(), 1);
        assert!(requests[0].0.starts_with(&format!("GET /v1/drafts/{id} ")));
        let headers = requests[0].0.to_lowercase();
        assert!(headers.contains("cookie: auth_refresh_token=synthetic-cookie"));
        assert!(!headers.contains("authorization:"));
        assert!(
            !c.ciphertext_snapshot()
                .to_string()
                .contains("Synthetic draft")
        );
    }
// contract-test: supporting surface=sdks.rust assertions=auth.session.authoritative-enforcement,sync.client.shared-rust-policy
    #[tokio::test]
    async fn null_rest_clears_only_ciphertext_and_regression_or_cross_chat_does_not_commit() {
        let id = "11111111-1111-4111-8111-111111111111";
        for response in [
            json!({"draft":null}),
            json!({"draft":{"chat_id":"22222222-2222-4222-8222-222222222222","encrypted_draft_md":"opaque","draft_v":4}}),
            json!({"draft":{"chat_id":id,"encrypted_draft_md":row(id)["encrypted_draft_md"],"draft_v":2}}),
        ] {
            let (api, peer) = crate::sdk::tests::server(vec![(200, response.clone())]).await;
            let mut session = super::super::sdk_boundary_tests::session();
            session.api_url = api.clone();
            let mut c = Client::new(&api, Some(session)).unwrap();
            c.user = json!({"id":"synthetic-owner"});
            let mut cached = row(id);
            cached["messages_v"] = json!(7);
            c.chats.insert(id.into(), cached);
            c.history.insert(id.into(), vec![json!({"id":"message"})]);
            let before = c.ciphertext_snapshot();
            let result = c.get_draft(id, true).await;
            if response["draft"].is_null() {
                assert!(result.unwrap().is_none());
                assert!(c.chats[id].get("encrypted_draft_md").is_none());
                assert_eq!(c.chats[id]["draft_v"], 3);
                assert_eq!(c.chats[id]["messages_v"], 7);
                assert_eq!(c.history[id].len(), 1);
            } else {
                assert!(result.is_err());
                assert_eq!(c.ciphertext_snapshot()["chats"], before["chats"]);
                assert_eq!(c.ciphertext_snapshot()["history"], before["history"]);
            }
            assert_eq!(peer.await.unwrap().len(), 1);
        }
    }
}

#[cfg(test)]
#[path = "draft_read_protocol_tests.rs"]
mod protocol_tests;
