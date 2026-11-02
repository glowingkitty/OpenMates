//! Ordered live-sync selector DATA, never key/row/auth/coverage authority.
//! A map-only restored snapshot cannot reconstruct first-match alias order.
use super::*;
use super::embed_version::VersionReadScope;
use std::sync::Arc;
use zeroize::Zeroize;

const MAX_ROWS:usize=10_000;
pub(super) const MAX_SELECTOR_BYTES:usize=1024*1024;
fn unavailable()->Error{Error::Unavailable{code:"saved_embed_selector_order_unavailable",reason:"ORIGINAL_BOUNDED_PERSONAL_LIVE_EMBED_ORDER_REQUIRED"}}
fn identifier(value:&str)->bool{value.len()<=128&&value.bytes().all(|byte|byte.is_ascii_alphanumeric()||matches!(byte,b'-'|b'_'))}
fn field<'a>(row:&'a Value,name:&str)->Result<Option<&'a str>>{
    match row.get(name){None|Some(Value::Null)=>Ok(None),Some(Value::String(value))if identifier(value)=>Ok(Some(value)),_=>Err(Error::Protocol)}
}
#[derive(Clone,PartialEq,Eq)]
pub(super) struct Identity {embed:Option<String>,alias:Option<String>}
impl Identity {
    fn read(row:&Value)->Result<Self>{
        let embed=field(row,"embed_id")?;let alias=field(row,"id")?;
        if embed.is_none()&&alias.is_none(){return Err(Error::Protocol)}
        Ok(Self{embed:embed.map(str::to_owned),alias:alias.map(str::to_owned)})
    }
    fn target(&self)->&str{self.embed.as_deref().or(self.alias.as_deref()).unwrap_or("")}
    fn matches(&self,selector:&str)->bool{self.embed.as_deref().is_some_and(|id|id.starts_with(selector))||self.alias.as_deref().is_some_and(|id|id.starts_with(selector))}
    fn matches_row(&self,row:&Value)->Result<bool>{Ok(self.embed.as_deref()==field(row,"embed_id")?&&self.alias.as_deref()==field(row,"id")?)}
    pub(super) fn bytes(&self)->usize{64+self.embed.as_ref().map_or(0,String::len)+self.alias.as_ref().map_or(0,String::len)}
}
impl Drop for Identity {fn drop(&mut self){self.embed.zeroize();self.alias.zeroize();}}
#[derive(Clone)]
pub(super) struct SelectorFrames {rows:Vec<Identity>,pub(super) bytes:usize,disabled:bool}
impl Default for SelectorFrames {fn default()->Self{Self{rows:vec![],bytes:0,disabled:false}}}
impl SelectorFrames {
    /// Called only inside the actual existing socket/parser correlation branch.
    /// Exactly TS's content-sidecar sources; metadata/unknown frames add nothing.
    pub(super) fn observe(&mut self,kind:&str,payload:&Value){
        if self.disabled||!matches!(kind,"phase_1b_chat_content_ready"|"background_message_sync"){return}
        let Some(value)=payload.get("embeds").filter(|value|!value.is_null())else{return};
        let result=(||->Result<()>{
            for row in value.as_array().ok_or(Error::Protocol)?{
                if self.rows.len()>=MAX_ROWS{return Err(Error::Protocol)}
                let identity=Identity::read(row)?;
                self.bytes=self.bytes.checked_add(identity.bytes()).filter(|n|*n<=MAX_SELECTOR_BYTES).ok_or(Error::Protocol)?;
                self.rows.push(identity);
            }Ok(())
        })();
        if result.is_err(){self.rows.clear();self.disabled=true;}
    }
    pub(super) fn bind(mut self,client:&Client)->Result<SavedEmbedSelectors>{
        if self.disabled{return Err(unavailable())}
        client.verify_private_operation()?;client.require_canonical_read_profile()?;
        if client.team()?.is_some()||client.embeds.len()>MAX_ROWS{return Err(unavailable())}
        let owner=client.user["id"].as_str().or_else(||client.user["user_id"].as_str()).ok_or_else(unavailable)?;
        if !uuid::Uuid::parse_str(owner).is_ok_and(|value|value.to_string()==owner){return Err(unavailable())}
        if self.rows.iter().any(|row|!client.embeds.contains_key(row.target())){return Err(unavailable())}
        let mut identities=BTreeMap::new();
        for(id,row)in &client.embeds{
            if !identifier(id){return Err(unavailable())}
            let identity=Identity::read(row)?;
            self.bytes=self.bytes.checked_add(id.len()).and_then(|n|n.checked_add(identity.bytes())).filter(|n|*n<=MAX_SELECTOR_BYTES).ok_or_else(unavailable)?;
            identities.insert(id.clone(),identity);
        }
        Ok(SavedEmbedSelectors{rows:self.rows,identities,scope:VersionReadScope::begin(client)?})
    }
}
pub(super) struct SavedEmbedSelectors {rows:Vec<Identity>,pub(super) identities:BTreeMap<String,Identity>,scope:VersionReadScope}
impl SavedEmbedSelectors {
    fn check(&self,client:&Client)->Result<()>{
        client.verify_private_operation()?;self.scope.check(client)?;
        if self.identities.len()!=client.embeds.len(){return Err(unavailable())}
        for(id,identity)in &self.identities{
            if !client.embeds.get(id).map(|row|identity.matches_row(row)).transpose()?.unwrap_or(false){return Err(unavailable())}
        }Ok(())
    }
    fn select(&self,client:&Client,selector:&str)->Result<String>{
        self.check(client)?;
        if selector.is_empty()||selector.len()>128||selector.chars().any(char::is_control){return Err(Error::Invalid("A nonempty embed selector is required."))}
        // No lexicographic/unique-match substitution: TS Array.find selects the
        // FIRST row, and checks both fields even when embed_id already exists.
        let id=self.rows.iter().find(|row|row.matches(selector)).ok_or(Error::Invalid("Embed not found in the original live inventory."))?.target();
        if !uuid::Uuid::parse_str(id).is_ok_and(|value|value.to_string()==id){return Err(unavailable())}
        self.check(client)?;Ok(id.into())
    }
}
impl Drop for SavedEmbedSelectors {fn drop(&mut self){for(mut id,_)in std::mem::take(&mut self.identities){id.zeroize();}}}
impl Client {
    /// Select from genuine current live-sync arrival/alias DATA, then perform
    /// the existing fresh owner-admitted Personal read. Selection is not auth.
    /// No sync/fetch fallback, account enumeration, map/snapshot inference or key
    /// export occurs here. CLI option/output/Team integration remains separate.
    pub async fn saved_embed_selector(&mut self,selector:&str)->Result<saved_embed::SavedEmbedRead>{
        let original=self.saved_embed_selectors.clone().ok_or_else(unavailable)?;
        let id=original.select(self,selector)?;
        let read=self.saved_embed(&id).await?;
        if !self.saved_embed_selectors.as_ref().is_some_and(|current|Arc::ptr_eq(current,&original)){return Err(Error::Cancelled)}
        original.check(self)?;read.check(self)?;Ok(read)
    }
}
#[cfg(test)]
#[path="saved_embed_selector_tests.rs"]
mod tests;


// Optional authenticated-cache DATA. Ordinary snapshot restore never imports it.
// Unknown legacy timestamps/order stay readable but cannot silently cause sync.
pub(super) const CACHE_FIELD:&str="saved_embed_order_v1";
pub(super) enum SelectorCache { Absent, Legacy, Ordered { at:u64, owner:String, frames:SelectorFrames, identities:BTreeMap<String,Identity> } }
#[derive(PartialEq,Eq,Debug)]
enum CacheDecision { Reuse, Sync }
impl SelectorCache {
    fn decision(&self,now:u64,empty:bool)->Result<CacheDecision>{
        match self {
            Self::Absent=>Ok(CacheDecision::Sync),
            Self::Legacy=>Err(unavailable()),
            Self::Ordered{at,..}=>{
                let age=now.checked_sub(*at).ok_or_else(unavailable)?;
                // Under one minute both maintained TS TTL branches reuse.
                // Pending-recovery cache TTL 60–300s is not yet represented;
                // never invent a pending flag or fetch while TS might reuse.
                if age<60_000 {Ok(CacheDecision::Reuse)}
                else if age>=300_000&&empty {Ok(CacheDecision::Sync)}
                else {Err(unavailable())}
            }
        }
    }
    pub(super) fn snapshot(&self,empty:bool)->Option<Value>{
        if matches!(self,Self::Absent)&&empty{return Some(json!({"version":1,"state":"unsynced"}))}
        let Self::Ordered{at,owner,frames,identities}=self else{return None};
        if frames.disabled{return None}
        Some(json!({"version":1,"synced_at":at,"owner":owner,"rows":frames.rows.iter().map(|row|json!({"embed_id":row.embed,"id":row.alias})).collect::<Vec<_>>(),"inventory":identities.iter().map(|(id,row)|(id.clone(),json!({"embed_id":row.embed,"id":row.alias}))).collect::<serde_json::Map<_,_>>()}))
    }
    pub(super) fn restore(value:Option<&Value>,empty:bool)->Self{
        let parse=||->Result<Self>{
            let value=value.ok_or_else(unavailable)?;
            let obj=value.as_object().ok_or(Error::Protocol)?;
            if obj.len()==2&&value["version"]==1&&value["state"]=="unsynced" {
                return if empty{Ok(Self::Absent)}else{Err(Error::Protocol)};
            }
            if obj.len()!=5||value["version"]!=1{return Err(Error::Protocol)}
            let at=value["synced_at"].as_u64().filter(|at|*at>0).ok_or(Error::Protocol)?;
            let owner=value["owner"].as_str().filter(|id|uuid::Uuid::parse_str(id).is_ok_and(|v|v.to_string()==*id)).ok_or(Error::Protocol)?.to_owned();
            let rows=value["rows"].as_array().ok_or(Error::Protocol)?;
            if rows.len()>MAX_ROWS{return Err(Error::Protocol)}
            let mut frames=SelectorFrames::default();
            for row in rows {
                if row.as_object().is_none_or(|row|row.len()!=2){return Err(Error::Protocol)}
                let identity=Identity::read(row)?;
                frames.bytes=frames.bytes.checked_add(identity.bytes()).filter(|n|*n<=MAX_SELECTOR_BYTES).ok_or(Error::Protocol)?;
                frames.rows.push(identity);
            }
            let map=value["inventory"].as_object().filter(|map|map.len()<=MAX_ROWS).ok_or(Error::Protocol)?;
            let mut identities=BTreeMap::new();
            for(id,row)in map {
                if !identifier(id)||row.as_object().is_none_or(|row|row.len()!=2){return Err(Error::Protocol)}
                let identity=Identity::read(row)?;
                frames.bytes=frames.bytes.checked_add(id.len()).and_then(|n|n.checked_add(identity.bytes())).filter(|n|*n<=MAX_SELECTOR_BYTES).ok_or(Error::Protocol)?;
                identities.insert(id.clone(),identity);
            }
            if frames.bytes>MAX_SELECTOR_BYTES-512{return Err(Error::Protocol)}
            Ok(Self::Ordered{at,owner,frames,identities})
        };
        parse().unwrap_or(Self::Legacy)
    }
}
impl Client {
    // Actual loaded content, not a caller cache-present/freshness flag. This
    // narrow producer preserves only genuine never-synced EMPTY native state.
    pub(super) fn saved_embed_unsynced_empty(&self)->bool{
        self.chats.is_empty()&&self.embeds.is_empty()&&self.wrappers.is_empty()
        &&self.history.is_empty()&&self.embed_keys.is_empty()&&self.sync_message_windows.is_empty()
        &&self.selected_first_pages.is_empty()&&self.team_wrapped_key.is_none()
    }
    /// Explicit native Cookie share preparation. Existing authenticated native
    /// cache restoration is the only importer of persisted ordered DATA. Cold
    /// absence performs one normal sync; supported fresh order performs none.
    /// Old map-only/ambiguous TTL/nonempty stale carry-forward remain gaps.
    /// No caller freshness flag, default fetch, key or source authority is added.
    pub async fn ensure_saved_embed_selector(&mut self)->Result<()> {
        self.require_session()?;self.verify_private_operation()?;self.require_canonical_read_profile()?;
        if self.team()?.is_some(){return Err(unavailable())}
        if let SelectorCache::Ordered{owner,..}=&self.saved_embed_cache {
            if self.user["id"].as_str().or_else(||self.user["user_id"].as_str())!=Some(owner.as_str()){return Err(Error::Cancelled)}
        }
        match self.saved_embed_cache.decision(now_ms(),self.embeds.is_empty())? {
            CacheDecision::Sync=>{
                if matches!(self.saved_embed_cache,SelectorCache::Absent)&&!self.saved_embed_unsynced_empty(){return Err(unavailable())}
                self.refresh_chat_metadata(0).await?;
            },
            CacheDecision::Reuse=>{
                let SelectorCache::Ordered{frames,identities,..}=&self.saved_embed_cache else{return Err(unavailable())};
                if identities.len()!=self.embeds.len(){return Err(unavailable())}
                for(id,identity)in identities {
                    if !self.embeds.get(id).map(|row|identity.matches_row(row)).transpose()?.unwrap_or(false){return Err(unavailable())}
                }
                self.saved_embed_selectors=Some(Arc::new(frames.clone().bind(self)?));
            }
        }
        self.saved_embed_selectors.as_ref().ok_or_else(unavailable)?.check(self)
    }
}

impl Drop for SelectorCache {
    fn drop(&mut self){if let Self::Ordered{owner,identities,..}=self{owner.zeroize();for(mut id,_)in std::mem::take(identities){id.zeroize();}}}
}
