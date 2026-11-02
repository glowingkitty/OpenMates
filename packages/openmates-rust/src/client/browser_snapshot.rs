//! Browser-only encrypted host preparation. Never native credential export/ACK.
use super::*;
use serde::{Serialize, Deserialize};
const MAX_SAFE: u64 = 9_007_199_254_740_991;
#[derive(Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all="camelCase", deny_unknown_fields)]
pub struct BrowserSealedCredentials {
    version: u8, owner: String, generation: u64, credential_revision: u64,
    api_endpoint: String, app_origin: String, snapshot_id: String,
    ciphertext: String, ciphertext_sha256: String,
}
#[derive(Serialize, Deserialize, PartialEq)]
#[serde(rename_all="camelCase", deny_unknown_fields)]
struct Payload {
    version: u8, owner: String, generation: u64, credential_revision: u64,
    api_endpoint: String, app_origin: String, snapshot_id: String,
    session_id: String, ws_token: String, hashed_email: String, user_email_salt: String,
}
impl Drop for Payload {
    fn drop(&mut self) { self.session_id.zeroize(); self.ws_token.zeroize(); self.hashed_email.zeroize(); self.user_email_salt.zeroize(); }
}
// A typed Drop guard owns EVERY decrypted credential JSON buffer, including
// parse-error/early-refusal paths; parsed Payload separately wipes its strings.
fn decrypt_browser_credential_json(ciphertext:&str,master:&[u8;32])->Result<zeroize::Zeroizing<Vec<u8>>>{
    crypto::decrypt_bytes(ciphertext,master)
}
fn has_canonical_envelope(account:&Value)->bool { account.get("encrypted_email_with_master_key").and_then(Value::as_str).is_some_and(|v| !v.is_empty()) }
impl Client {
    fn capture_browser_crypto_operation(&self)->Result<CancellationToken> {
        let token=self.operation_cancel.clone();
        self.check_browser_crypto_operation(&token)?;Ok(token)
    }
    fn check_browser_crypto_operation(&self,token:&CancellationToken)->Result<()> {
        if token.is_cancelled()||self.operation_cancel.is_cancelled()||self.operation_cancel!=*token {return Err(Error::Cancelled);}
        Ok(())
    }

    fn browser_snapshot_payload(&self, snapshot_id: String) -> Result<Payload> {
        if self.browser_local_read_only{return Err(Error::Unavailable{code:"browser_offline_read_only",reason:"LOCAL_PROFILE_DOES_NOT_GRANT_SERVER_OR_PERSISTENCE_AUTHORITY"});}
        let authority=self.browser_authority.as_ref().ok_or(Error::Forbidden)?;
        if authority.persistence != BrowserPersistence::Persisted || self.generation>MAX_SAFE || self.credential_revision>MAX_SAFE { return Err(Error::Forbidden); }
        let session=self.require_credentials()?;
        if self.user["id"].as_str()!=Some(authority.principal.as_str()) || session.active_team_id.is_some() { return Err(Error::Forbidden); }
        let token=session.ws_token.as_ref().filter(|s| !s.is_empty() && s.len()<=4096).ok_or(Error::Authentication)?;
        let app_origin=self.options.app_url.as_ref().ok_or(Error::Forbidden)?;
        let payload=Payload {version:1,owner:authority.principal.clone(),generation:self.generation,credential_revision:self.credential_revision,
            api_endpoint:self.base.to_string().trim_end_matches('/').into(),app_origin:app_origin.clone(),snapshot_id,
            session_id:session.session_id.clone(),ws_token:token.clone(),hashed_email:session.hashed_email.clone(),user_email_salt:session.user_email_salt.clone()};
        if payload.session_id.len()>128 || payload.hashed_email.len()>512 || payload.user_email_salt.len()>512 { return Err(Error::Protocol); }
        Ok(payload)
    }
    /// Seals only browser transport credentials inside the admitted Rust owner.
    /// Cookie authority/master/native Session are never serialized/exported.
    /// Legacy absent canonical envelopes refuse this stronger preparation.
    pub async fn prepare_browser_credential_snapshot(&mut self) -> Result<BrowserSealedCredentials> {
        let operation=self.capture_browser_crypto_operation()?;
        self.require_browser_owner_guards()?;
        let before=self.browser_snapshot_payload(uuid::Uuid::new_v4().to_string())?;
        let session=self.require_credentials()?;
        let profile=BrowserProfileKey{principal:before.owner.clone(),master:self.master_capability()?,hashed_email:session.hashed_email.clone(),user_email_salt:session.user_email_salt.clone(),persistence:BrowserPersistence::Persisted,paired_session_expires_at:session.paired_session_expires_at};
        let binding=self.master_binding()?;
        let account=self.request(Method::GET,"/v1/auth/pair/v2/account-check",None).await;
        self.check_browser_crypto_operation(&operation)?;
        let account=account?;
        let validated=validate_browser_account_profile_async(&profile,&account).await;
        self.check_browser_crypto_operation(&operation)?;
        validated?;
        binding.check(self)?;
        if !has_canonical_envelope(&account) { return Err(Error::Authentication); }
        // Credential refresh during the authenticated check requires a new exact snapshot.
        let current=self.browser_snapshot_payload(before.snapshot_id.clone())?;
        if current!=before { return Err(Error::Cancelled); }
        let plain=zeroize::Zeroizing::new(serde_json::to_vec(&current).map_err(|_|Error::Protocol)?);
        if plain.len()>8192 { return Err(Error::Protocol); }
        let ciphertext=self.master_capability()?.encrypt_bytes(&plain).await;
        self.check_browser_crypto_operation(&operation)?;
        let ciphertext=ciphertext?;
        binding.check(self)?;
        if self.browser_snapshot_payload(current.snapshot_id.clone())?!=current{return Err(Error::Cancelled);}
        self.check_browser_crypto_operation(&operation)?;
        Ok(BrowserSealedCredentials {version:1,owner:current.owner.clone(),generation:current.generation,credential_revision:current.credential_revision,
            api_endpoint:current.api_endpoint.clone(),app_origin:current.app_origin.clone(),snapshot_id:current.snapshot_id.clone(),ciphertext_sha256:sha256(&ciphertext),ciphertext})
    }
    /// Validates exact current bytes after a host commit. This is deliberately
    /// NOT acknowledge_credentials: cross-DB/key/cookie writer coherence is OPEN.
    pub fn validate_browser_credential_snapshot(&self, sealed: &BrowserSealedCredentials) -> Result<()> {
        if sealed.version!=1 || sealed.ciphertext.len()>12*1024 || sha256(&sealed.ciphertext)!=sealed.ciphertext_sha256 { return Err(Error::Protocol); }
        uuid::Uuid::parse_str(&sealed.snapshot_id).map_err(|_|Error::Protocol)?;
        let expected=self.browser_snapshot_payload(sealed.snapshot_id.clone())?;
        let plain=decrypt_browser_credential_json(&sealed.ciphertext,self.native_master_key()?)?;
        if plain.len()>8192 { return Err(Error::Protocol); }
        let payload:Payload=serde_json::from_slice(&plain).map_err(|_|Error::Protocol)?;
        if payload!=expected || sealed.owner!=expected.owner || sealed.generation!=expected.generation || sealed.credential_revision!=expected.credential_revision
            || sealed.api_endpoint!=expected.api_endpoint || sealed.app_origin!=expected.app_origin { return Err(Error::Cancelled); }
        Ok(())
    }
    pub async fn validate_browser_credential_snapshot_async(&self, sealed: &BrowserSealedCredentials) -> Result<()> {
        let operation=self.capture_browser_crypto_operation()?;
        if sealed.version!=1 || sealed.ciphertext.len()>12*1024 || sha256(&sealed.ciphertext)!=sealed.ciphertext_sha256 { return Err(Error::Protocol); }
        uuid::Uuid::parse_str(&sealed.snapshot_id).map_err(|_|Error::Protocol)?;
        let expected=self.browser_snapshot_payload(sealed.snapshot_id.clone())?;
        let binding=self.master_binding()?;
        let plain=self.master_capability()?.decrypt_bytes(&sealed.ciphertext).await;
        self.check_browser_crypto_operation(&operation)?;
        let plain=plain?;
        binding.check(self)?;
        if self.browser_snapshot_payload(sealed.snapshot_id.clone())?!=expected{return Err(Error::Cancelled);}
        if plain.len()>8192 { return Err(Error::Protocol); }
        let payload:Payload=serde_json::from_slice(&plain).map_err(|_|Error::Protocol)?;
        if payload!=expected || sealed.owner!=expected.owner || sealed.generation!=expected.generation || sealed.credential_revision!=expected.credential_revision
            || sealed.api_endpoint!=expected.api_endpoint || sealed.app_origin!=expected.app_origin { return Err(Error::Cancelled); }
        self.check_browser_crypto_operation(&operation)?;
        Ok(())
    }
}

/// Host scope is correlation, never proof of WebLock ownership/key association.
#[derive(Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all="camelCase", deny_unknown_fields)]
pub struct BrowserCredentialCasScope { lifecycle_generation:u64, workspace_epoch:u64 }
#[derive(Serialize)]
#[serde(tag="kind", rename_all="snake_case", rename_all_fields="camelCase")]
pub enum BrowserCredentialCasEffect {
    Read { operation_id:String,owner:String,api_endpoint:String,app_origin:String },
    Cas { operation_id:String,expected:Option<BrowserSealedCredentials>,next:BrowserSealedCredentials },
}
/// Platform IO evidence only; this cannot authorize a native credential ACK.
#[derive(Serialize,Deserialize)]
#[serde(tag="kind", rename_all="snake_case", rename_all_fields="camelCase",deny_unknown_fields)]
pub enum BrowserCredentialCasIoReceipt {
    Read { operation_id:String,snapshot:Option<BrowserSealedCredentials>,transaction_committed:bool,owner_row_atomic:bool,cross_database_association_proven:bool,credential_acknowledged:bool },
    Cas { operation_id:String,expected:Option<BrowserSealedCredentials>,snapshot:BrowserSealedCredentials,transaction_committed:bool,owner_row_atomic:bool,cross_database_association_proven:bool,credential_acknowledged:bool },
}
/// Nonserializable/noncloneable one-use capability, retained inside Rust only.
pub struct BrowserCredentialCasOperation {
    operation_id:String,scope:BrowserCredentialCasScope,owner:String,generation:u64,
    api_endpoint:String,app_origin:String,session_id:zeroize::Zeroizing<String>,
    master:credentials::MasterBinding,cancel:CancellationToken,
}
pub struct BrowserPreparedCredentialCas {
    operation:BrowserCredentialCasOperation,expected:Option<BrowserSealedCredentials>,next:BrowserSealedCredentials,
}
#[derive(Serialize)]
#[serde(rename_all="camelCase")]
pub struct BrowserCredentialCasValidation {
    operation_id:String,scope:BrowserCredentialCasScope,snapshot_id:String,ciphertext_sha256:String,
    cross_database_association_proven:bool,credential_acknowledged:bool,
}
impl BrowserCredentialCasOperation {
    pub fn read_effect(&self)->BrowserCredentialCasEffect {
        BrowserCredentialCasEffect::Read {operation_id:self.operation_id.clone(),owner:self.owner.clone(),api_endpoint:self.api_endpoint.clone(),app_origin:self.app_origin.clone()}
    }
    fn current(&self,client:&Client)->Result<()> {
        if self.cancel.is_cancelled()||client.operation_cancel!=self.cancel||client.generation!=self.generation {return Err(Error::Cancelled);}
        let payload=client.browser_snapshot_payload(self.operation_id.clone())?;
        self.master.check(client)?;
        if payload.owner!=self.owner||payload.api_endpoint!=self.api_endpoint||payload.app_origin!=self.app_origin||payload.session_id.as_str()!=self.session_id.as_str(){return Err(Error::Cancelled);}
        Ok(())
    }
}
impl BrowserPreparedCredentialCas {
    pub fn readback_effect(&self)->BrowserCredentialCasEffect {self.operation.read_effect()}
    pub fn effect(&self)->BrowserCredentialCasEffect {
        BrowserCredentialCasEffect::Cas {operation_id:self.operation.operation_id.clone(),expected:self.expected.clone(),next:self.next.clone()}
    }
}
impl Client {
    pub fn begin_browser_credential_cas(&self,scope:BrowserCredentialCasScope)->Result<BrowserCredentialCasOperation>{
        self.require_browser_owner_guards()?;
        if scope.lifecycle_generation==0||scope.lifecycle_generation>MAX_SAFE||scope.workspace_epoch>MAX_SAFE{return Err(Error::Protocol);}
        let payload=self.browser_snapshot_payload(uuid::Uuid::new_v4().to_string())?;
        if self.operation_cancel.is_cancelled(){return Err(Error::Cancelled);}
        Ok(BrowserCredentialCasOperation {operation_id:payload.snapshot_id.clone(),scope,owner:payload.owner.clone(),generation:payload.generation,
            api_endpoint:payload.api_endpoint.clone(),app_origin:payload.app_origin.clone(),session_id:zeroize::Zeroizing::new(payload.session_id.clone()),master:self.master_binding()?,cancel:self.operation_cancel.clone()})
    }
    /// Predecessor fields are authenticated history, never live credentials.
    fn validate_browser_credential_history(&self,sealed:&BrowserSealedCredentials)->Result<()> {
        if sealed.version!=1||sealed.ciphertext.len()>12*1024||sha256(&sealed.ciphertext)!=sealed.ciphertext_sha256{return Err(Error::Protocol);}
        uuid::Uuid::parse_str(&sealed.snapshot_id).map_err(|_|Error::Protocol)?;
        let plain=decrypt_browser_credential_json(&sealed.ciphertext,self.native_master_key()?)?;
        if plain.len()>8192{return Err(Error::Protocol);}
        let old:Payload=serde_json::from_slice(&plain).map_err(|_|Error::Protocol)?;
        let current=self.browser_snapshot_payload(sealed.snapshot_id.clone())?;
        if old.version!=1||old.owner!=current.owner||old.api_endpoint!=current.api_endpoint||old.app_origin!=current.app_origin
            ||old.snapshot_id!=sealed.snapshot_id||old.owner!=sealed.owner||old.api_endpoint!=sealed.api_endpoint||old.app_origin!=sealed.app_origin
            ||old.generation!=sealed.generation||old.credential_revision!=sealed.credential_revision||old.generation==0||old.generation>MAX_SAFE||old.credential_revision==0||old.credential_revision>MAX_SAFE
            ||old.session_id.is_empty()||old.session_id.len()>128||old.ws_token.is_empty()||old.ws_token.len()>4096||old.hashed_email.is_empty()||old.hashed_email.len()>512||old.user_email_salt.is_empty()||old.user_email_salt.len()>512{return Err(Error::Protocol);}
        Ok(())
    }
    async fn validate_browser_credential_history_async(&self,sealed:&BrowserSealedCredentials)->Result<()> {
        let operation=self.capture_browser_crypto_operation()?;
        if sealed.version!=1||sealed.ciphertext.len()>12*1024||sha256(&sealed.ciphertext)!=sealed.ciphertext_sha256{return Err(Error::Protocol);}
        uuid::Uuid::parse_str(&sealed.snapshot_id).map_err(|_|Error::Protocol)?;
        let binding=self.master_binding()?;
        let before=self.browser_snapshot_payload(sealed.snapshot_id.clone())?;
        let plain=self.master_capability()?.decrypt_bytes(&sealed.ciphertext).await;
        self.check_browser_crypto_operation(&operation)?;
        let plain=plain?;
        binding.check(self)?;
        if self.browser_snapshot_payload(sealed.snapshot_id.clone())?!=before{return Err(Error::Cancelled);}
        if plain.len()>8192{return Err(Error::Protocol);}
        let old:Payload=serde_json::from_slice(&plain).map_err(|_|Error::Protocol)?;
        let current=self.browser_snapshot_payload(sealed.snapshot_id.clone())?;
        if old.version!=1||old.owner!=current.owner||old.api_endpoint!=current.api_endpoint||old.app_origin!=current.app_origin
            ||old.snapshot_id!=sealed.snapshot_id||old.owner!=sealed.owner||old.api_endpoint!=sealed.api_endpoint||old.app_origin!=sealed.app_origin
            ||old.generation!=sealed.generation||old.credential_revision!=sealed.credential_revision||old.generation==0||old.generation>MAX_SAFE||old.credential_revision==0||old.credential_revision>MAX_SAFE
            ||old.session_id.is_empty()||old.session_id.len()>128||old.ws_token.is_empty()||old.ws_token.len()>4096||old.hashed_email.is_empty()||old.hashed_email.len()>512||old.user_email_salt.is_empty()||old.user_email_salt.len()>512{return Err(Error::Protocol);}
        self.check_browser_crypto_operation(&operation)?;
        Ok(())
    }
    pub async fn prepare_browser_credential_cas(&mut self,operation:BrowserCredentialCasOperation,read:BrowserCredentialCasIoReceipt)->Result<BrowserPreparedCredentialCas>{
        operation.current(self)?;
        let expected=match read {
            BrowserCredentialCasIoReceipt::Read {operation_id,snapshot,transaction_committed:true,owner_row_atomic:true,cross_database_association_proven:false,credential_acknowledged:false} if operation_id==operation.operation_id=>snapshot,
            _=>return Err(Error::Protocol),
        };
        self.validate_session().await?;operation.current(self)?;
        let next=self.prepare_browser_credential_snapshot().await?;operation.current(self)?;
        if let Some(old)=expected.as_ref(){self.validate_browser_credential_history_async(old).await?;}
        Ok(BrowserPreparedCredentialCas{operation,expected,next})
    }
    /// Consumes pending capability even on refusal; never advances ACK/ledger.
    pub fn finish_browser_credential_cas(&self,prepared:BrowserPreparedCredentialCas,receipt:BrowserCredentialCasIoReceipt,readback:BrowserCredentialCasIoReceipt)->Result<BrowserCredentialCasValidation>{
        prepared.operation.current(self)?;
        self.validate_browser_credential_snapshot(&prepared.next)?;
        self.finish_browser_credential_receipts(prepared,receipt,readback)
    }
    pub async fn finish_browser_credential_cas_async(&self,prepared:BrowserPreparedCredentialCas,receipt:BrowserCredentialCasIoReceipt,readback:BrowserCredentialCasIoReceipt)->Result<BrowserCredentialCasValidation>{
        prepared.operation.current(self)?;
        self.validate_browser_credential_snapshot_async(&prepared.next).await?;
        prepared.operation.current(self)?;
        self.finish_browser_credential_receipts(prepared,receipt,readback)
    }
    fn finish_browser_credential_receipts(&self,prepared:BrowserPreparedCredentialCas,receipt:BrowserCredentialCasIoReceipt,readback:BrowserCredentialCasIoReceipt)->Result<BrowserCredentialCasValidation>{
        match receipt {
            BrowserCredentialCasIoReceipt::Cas {operation_id,expected,snapshot,transaction_committed:true,owner_row_atomic:true,cross_database_association_proven:false,credential_acknowledged:false}
                if operation_id==prepared.operation.operation_id&&expected==prepared.expected&&snapshot==prepared.next=>{},
            _=>return Err(Error::Conflict),
        }
        match readback {
            BrowserCredentialCasIoReceipt::Read {operation_id,snapshot:Some(snapshot),transaction_committed:true,owner_row_atomic:true,cross_database_association_proven:false,credential_acknowledged:false}
                if operation_id==prepared.operation.operation_id&&snapshot==prepared.next=>{},
            _=>return Err(Error::Conflict),
        }
        Ok(BrowserCredentialCasValidation {operation_id:prepared.operation.operation_id,scope:prepared.operation.scope,
            snapshot_id:prepared.next.snapshot_id,ciphertext_sha256:prepared.next.ciphertext_sha256,
            cross_database_association_proven:false,credential_acknowledged:false})
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    const OWNER:&str="11111111-1111-4111-8111-111111111111";
    fn client()->Client {
        let session=Session {api_url:"http://127.0.0.1:8000".into(),session_id:OWNER.into(),cookies:BTreeMap::new(),ws_token:Some("synthetic-token".into()),master_key:zeroize::Zeroizing::new([7;32]),hashed_email:"synthetic-hash".into(),user_email_salt:"synthetic-salt".into(),email_encryption_key:None,created_at:now_ms(),paired_session_expires_at:None,active_team_id:None};
        let mut client=Client::with_options("http://127.0.0.1:8000",Some(session),ClientOptions{app_url:Some("http://localhost:5173".into()),..Default::default()}).unwrap();
        client.user=json!({"id":OWNER});client.browser_authority=Some(BrowserAuthority{principal:OWNER.into(),persistence:BrowserPersistence::Persisted,owner_guards:true});client.generation=2;client.credential_revision=3;client.credential_ack=0;client
    }
    fn sealed(client:&Client)->BrowserSealedCredentials {
        let p=client.browser_snapshot_payload("22222222-2222-4222-8222-222222222222".into()).unwrap();
        let bytes=zeroize::Zeroizing::new(serde_json::to_vec(&p).unwrap());
        let ciphertext=crypto::encrypt_bytes(&bytes,&client.require_session().unwrap().master_key).unwrap();
        BrowserSealedCredentials{version:1,owner:p.owner.clone(),generation:p.generation,credential_revision:p.credential_revision,api_endpoint:p.api_endpoint.clone(),app_origin:p.app_origin.clone(),snapshot_id:p.snapshot_id.clone(),ciphertext_sha256:sha256(&ciphertext),ciphertext}
    }
    #[test]
    fn browser_sealed_bytes_validate_but_never_ack_or_export_native_session(){
        let c=client();let sealed=sealed(&c);c.validate_browser_credential_snapshot(&sealed).unwrap();
        assert_eq!(c.credential_ack,0);assert!(c.credential_snapshot().is_none());assert!(c.clone_session().is_none());
        let out=serde_json::to_string(&sealed).unwrap();for secret in ["synthetic-token","synthetic-hash","synthetic-salt","masterKey","cookies","sessionId"]{assert!(!out.contains(secret));}
    }
    #[test]
    fn browser_sealed_snapshot_refuses_generation_revision_key_or_context_drift(){
        for case in 0..5{let mut c=client();let s=sealed(&c);match case{0=>c.generation+=1,1=>c.credential_revision+=1,2=>c.session.as_mut().unwrap().master_key=zeroize::Zeroizing::new([8;32]),3=>c.options.app_url=Some("http://localhost:5174".into()),_=>c.session.as_mut().unwrap().ws_token=Some("changed".into())};assert!(c.validate_browser_credential_snapshot(&s).is_err());assert_eq!(c.credential_ack,0);}
    }
    #[test]
    fn browser_sealed_snapshot_refuses_tampered_owner_digest_or_extra_fields(){
        let c=client();let s=sealed(&c);let text=serde_json::to_string(&s).unwrap();
        let mut value:Value=serde_json::from_str(&text).unwrap();value["masterKey"]=json!("forbidden");assert!(serde_json::from_value::<BrowserSealedCredentials>(value).is_err());
        let mut owner:BrowserSealedCredentials=serde_json::from_str(&text).unwrap();owner.owner="33333333-3333-4333-8333-333333333333".into();assert!(c.validate_browser_credential_snapshot(&owner).is_err());
        let mut digest:BrowserSealedCredentials=serde_json::from_str(&text).unwrap();digest.ciphertext_sha256="0".repeat(64);assert!(c.validate_browser_credential_snapshot(&digest).is_err());
    }
    #[test]
    fn durable_preparation_requires_existing_canonical_envelope(){
        for account in [json!({}),json!({"encrypted_email_with_master_key":null}),json!({"encrypted_email_with_master_key":""})]{assert!(!has_canonical_envelope(&account));}
        assert!(has_canonical_envelope(&json!({"encrypted_email_with_master_key":"existing-ciphertext"})));
    }
    #[test]
    fn memory_only_and_native_authority_cannot_prepare_durable_browser_payload(){
        let mut c=client();c.browser_authority.as_mut().unwrap().persistence=BrowserPersistence::MemoryOnly;assert!(c.browser_snapshot_payload(OWNER.into()).is_err());
        c.browser_authority=None;assert!(c.browser_snapshot_payload(OWNER.into()).is_err());assert!(c.credential_snapshot().is_some());
    }    fn cas_scope()->BrowserCredentialCasScope{BrowserCredentialCasScope{lifecycle_generation:4,workspace_epoch:7}}
    fn pending_cas(c:&Client,expected:Option<BrowserSealedCredentials>)->BrowserPreparedCredentialCas{
        BrowserPreparedCredentialCas{operation:c.begin_browser_credential_cas(cas_scope()).unwrap(),expected,next:sealed(c)}
    }
    fn cas_receipt(p:&BrowserPreparedCredentialCas)->BrowserCredentialCasIoReceipt{
        BrowserCredentialCasIoReceipt::Cas{operation_id:p.operation.operation_id.clone(),expected:p.expected.clone(),snapshot:p.next.clone(),transaction_committed:true,owner_row_atomic:true,cross_database_association_proven:false,credential_acknowledged:false}
    }
    fn cas_readback(p:&BrowserPreparedCredentialCas)->BrowserCredentialCasIoReceipt{
        BrowserCredentialCasIoReceipt::Read{operation_id:p.operation.operation_id.clone(),snapshot:Some(p.next.clone()),transaction_committed:true,owner_row_atomic:true,cross_database_association_proven:false,credential_acknowledged:false}
    }
    #[test]
    fn cas_exact_bytes_consume_without_native_snapshot_or_ack(){
        let c=client();let p=pending_cas(&c,None);let receipt=cas_receipt(&p);let readback=cas_readback(&p);
        let result=c.finish_browser_credential_cas(p,receipt,readback).unwrap();
        assert!(!result.credential_acknowledged&&!result.cross_database_association_proven);assert_eq!(c.credential_ack,0);assert!(c.credential_snapshot().is_none());
    }
    #[test]
    fn cas_foreign_client_same_fields_cannot_consume_capability(){
        let c=client();let p=pending_cas(&c,None);let receipt=cas_receipt(&p);let readback=cas_readback(&p);
        assert!(matches!(client().finish_browser_credential_cas(p,receipt,readback),Err(Error::Cancelled)));
    }
    #[test]
    fn cas_old_generation_revision_and_token_are_history_only(){
        let c=client();let mut old=client();old.generation=900;old.credential_revision=800;
        old.session.as_mut().unwrap().ws_token=Some("OLD_HISTORY_ONLY".into());let old=sealed(&old);
        c.validate_browser_credential_history(&old).unwrap();assert!(c.validate_browser_credential_snapshot(&old).is_err());
        assert_eq!(c.require_session().unwrap().ws_token.as_deref(),Some("synthetic-token"));assert_eq!(c.generation,2);assert_eq!(c.credential_revision,3);
    }
    #[test]
    fn cas_history_wrong_key_owner_origin_or_bytes_refuses(){
        for mode in 0..4{let c=client();let mut old=client();let mut stored=sealed(&old);
            match mode{0=>{old.session.as_mut().unwrap().master_key=zeroize::Zeroizing::new([8;32]);stored=sealed(&old);},1=>stored.owner="33333333-3333-4333-8333-333333333333".into(),2=>stored.app_origin="http://localhost:5174".into(),_=>stored.ciphertext.push('A')}
            assert!(c.validate_browser_credential_history(&stored).is_err());assert_eq!(c.credential_ack,0);
        }
    }
    #[test]
    fn cas_exact_predecessor_next_operation_and_false_only_receipt_are_required(){
        for mode in 0..5{let c=client();let p=pending_cas(&c,Some(sealed(&c)));let mut receipt=cas_receipt(&p);let readback=cas_readback(&p);
            if let BrowserCredentialCasIoReceipt::Cas{operation_id,expected,snapshot,cross_database_association_proven,credential_acknowledged,..}=&mut receipt{
                match mode{0=>*operation_id=uuid::Uuid::new_v4().to_string(),1=>*expected=None,2=>snapshot.ciphertext_sha256="0".repeat(64),3=>*cross_database_association_proven=true,_=>*credential_acknowledged=true}
            }
            assert!(matches!(c.finish_browser_credential_cas(p,receipt,readback),Err(Error::Conflict)));assert_eq!(c.credential_ack,0);
        }
    }
    #[test]
    fn cas_aba_generation_reset_or_live_token_change_refuses(){
        for mode in 0..3{let mut c=client();let p=pending_cas(&c,None);let receipt=cas_receipt(&p);let readback=cas_readback(&p);
            match mode{0=>{let generation=c.generation;c.clear_account_cache();c.generation=generation;c.user=json!({"id":OWNER});},1=>c.operation_cancel.cancel(),_=>c.session.as_mut().unwrap().ws_token=Some("changed-token".into())}
            assert!(c.finish_browser_credential_cas(p,receipt,readback).is_err());assert_eq!(c.credential_ack,0);
        }
    }
    #[tokio::test]
    async fn cas_read_receipt_cannot_claim_ack_or_another_operation(){
        let mut c=client();let op=c.begin_browser_credential_cas(cas_scope()).unwrap();
        let receipt=BrowserCredentialCasIoReceipt::Read{operation_id:op.operation_id.clone(),snapshot:None,transaction_committed:true,owner_row_atomic:true,cross_database_association_proven:false,credential_acknowledged:true};
        assert!(matches!(c.prepare_browser_credential_cas(op,receipt).await,Err(Error::Protocol)));assert_eq!(c.credential_ack,0);
    }
    #[test]
    fn cas_scope_is_bounded_closed_and_operation_capabilities_are_unique(){
        let c=client();assert!(serde_json::from_value::<BrowserCredentialCasScope>(json!({"lifecycleGeneration":1,"workspaceEpoch":0,"associationProven":true})).is_err());
        assert!(c.begin_browser_credential_cas(BrowserCredentialCasScope{lifecycle_generation:0,workspace_epoch:0}).is_err());
        let one=c.begin_browser_credential_cas(cas_scope()).unwrap();let two=c.begin_browser_credential_cas(cas_scope()).unwrap();assert_ne!(one.operation_id,two.operation_id);
    }
    #[tokio::test]
    async fn cas_real_fresh_proof_precedes_history_rotation_and_missing_envelope_refuses(){
        use tokio::io::{AsyncReadExt,AsyncWriteExt};
        for missing in [false,true]{
            let mut c=client();c.session.as_mut().unwrap().hashed_email=crypto::hash_email("cas-fixture@example.invalid");
            let envelope=crypto::encrypt_combined("cas-fixture@example.invalid",&c.require_session().unwrap().master_key).unwrap();
            let account=json!({"user_id":OWNER,"hashed_email":c.require_session().unwrap().hashed_email,"user_email_salt":c.require_session().unwrap().user_email_salt,"encrypted_email_with_master_key":if missing{Value::Null}else{json!(envelope)}});
            let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();let url=format!("http://{}",listener.local_addr().unwrap());
            c.base=url::Url::parse(&url).unwrap();c.session.as_mut().unwrap().api_url=url.clone();
            let mut old=client();old.base=c.base.clone();old.session.as_mut().unwrap().api_url=url.clone();old.generation=900;old.credential_revision=800;old.session.as_mut().unwrap().ws_token=Some("OLD_HISTORY_ONLY".into());let predecessor=sealed(&old);
            let peer=tokio::spawn(async move{
                let mut paths=Vec::new();
                for body in [json!({"success":true,"user":{"id":OWNER},"ws_token":"CURRENT_FRESH_TOKEN","client_security_capabilities":["expected-principal-v1","ws-dual-principal-v1"]}),account]{
                    let(mut socket,_)=listener.accept().await.unwrap();let mut bytes=Vec::new();
                    loop{let mut part=[0u8;1024];let count=socket.read(&mut part).await.unwrap();assert!(count>0);bytes.extend_from_slice(&part[..count]);assert!(bytes.len()<8192);
                        if let Some(end)=bytes.windows(4).position(|v|v==b"\r\n\r\n"){
                            let head=std::str::from_utf8(&bytes[..end]).unwrap();let length=head.lines().find_map(|line|line.to_ascii_lowercase().strip_prefix("content-length:").map(str::trim).and_then(|v|v.parse::<usize>().ok())).unwrap_or(0);
                            if bytes.len()>=end+4+length{paths.push(head.lines().next().unwrap().to_owned());break;}
                        }
                    }
                    let body=body.to_string();socket.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",body.len()).as_bytes()).await.unwrap();
                }paths
            });
            let operation=c.begin_browser_credential_cas(cas_scope()).unwrap();let read=BrowserCredentialCasIoReceipt::Read{operation_id:operation.operation_id.clone(),snapshot:Some(predecessor),transaction_committed:true,owner_row_atomic:true,cross_database_association_proven:false,credential_acknowledged:false};
            let prepared=crate::platform::time::timeout(Duration::from_secs(3),c.prepare_browser_credential_cas(operation,read)).await.unwrap();
            let paths=peer.await.unwrap();assert_eq!(paths,["POST /v1/auth/session HTTP/1.1","GET /v1/auth/pair/v2/account-check HTTP/1.1"]);
            if missing{assert!(matches!(prepared,Err(Error::Authentication)));}
            else{let prepared=prepared.unwrap();let receipt=cas_receipt(&prepared);let readback=cas_readback(&prepared);c.finish_browser_credential_cas(prepared,receipt,readback).unwrap();}
            assert_eq!(c.require_session().unwrap().ws_token.as_deref(),Some("CURRENT_FRESH_TOKEN"));assert_eq!(c.generation,2);assert_eq!(c.credential_ack,0);assert!(c.credential_snapshot().is_none());
        }
    }
    #[test]
    fn cas_subsequent_committed_readback_must_match_exact_next(){
        for mode in 0..3{let c=client();let p=pending_cas(&c,None);let receipt=cas_receipt(&p);let mut readback=cas_readback(&p);
            if let BrowserCredentialCasIoReceipt::Read{snapshot,operation_id,transaction_committed,..}=&mut readback{match mode{0=>*snapshot=None,1=>*operation_id=uuid::Uuid::new_v4().to_string(),_=>*transaction_committed=false}}
            assert!(matches!(c.finish_browser_credential_cas(p,receipt,readback),Err(Error::Conflict)));assert_eq!(c.credential_ack,0);
        }
    }
    #[test]
    fn decrypted_credential_json_has_type_level_zeroizing_owner(){
        let c=client();let sealed=sealed(&c);
        let mut guarded:zeroize::Zeroizing<Vec<u8>>=decrypt_browser_credential_json(&sealed.ciphertext,&c.require_session().unwrap().master_key).unwrap();
        let parsed:Payload=serde_json::from_slice(&guarded).unwrap();assert_eq!(parsed.ws_token,"synthetic-token");drop(parsed);
        guarded.zeroize();assert!(guarded.is_empty());
    }

    struct DelayedOpaqueAes {
        entered:tokio::sync::Notify,resume:tokio::sync::Notify,
        encrypt_gate:bool,decrypt_gate:bool,
    }
    impl crypto::master::MasterCrypto for DelayedOpaqueAes {
        fn encrypt<'a>(&'a self,iv:&'a [u8;12],plain:&'a [u8])->crypto::master::MasterCryptoFuture<'a>{Box::pin(async move{
            if self.encrypt_gate{self.entered.notify_one();self.resume.notified().await;}
            crypto::encrypt_aead(plain,&[7;32],iv,&[]).map(zeroize::Zeroizing::new)
        })}
        fn decrypt<'a>(&'a self,iv:&'a [u8;12],cipher:&'a [u8])->crypto::master::MasterCryptoFuture<'a>{Box::pin(async move{
            if self.decrypt_gate{self.entered.notify_one();self.resume.notified().await;}
            crypto::decrypt_aead(cipher,&[7;32],iv,&[])
        })}
    }
    fn opaque_client(mut c:Client,port:std::sync::Arc<DelayedOpaqueAes>)->Client {
        let native=c.session.take().unwrap();
        let mut credentials=credentials::BrowserCredentials::from_native_session(native);
        credentials.master=crypto::master::MasterCapability::opaque_for_test(port);
        c.browser_credentials=Some(credentials);c
    }
    fn legacy_cipher(plain:&[u8])->String {
        use base64::Engine;
        let iv=[3u8;12];let mut bytes=iv.to_vec();bytes.extend(crypto::encrypt_aead(plain,&[7;32],&iv,&[]).unwrap());base64::engine::general_purpose::STANDARD.encode(bytes)
    }
    fn opaque_sealed(c:&Client)->BrowserSealedCredentials {
        let payload=c.browser_snapshot_payload("22222222-2222-4222-8222-222222222222".into()).unwrap();
        let plain=zeroize::Zeroizing::new(serde_json::to_vec(&payload).unwrap());let ciphertext=legacy_cipher(&plain);
        BrowserSealedCredentials {version:1,owner:payload.owner.clone(),generation:payload.generation,credential_revision:payload.credential_revision,api_endpoint:payload.api_endpoint.clone(),app_origin:payload.app_origin.clone(),snapshot_id:payload.snapshot_id.clone(),ciphertext_sha256:sha256(&ciphertext),ciphertext}
    }
    #[tokio::test]
    async fn standalone_opaque_snapshot_validation_checks_cancel_after_unabortable_decrypt() {
        let port=std::sync::Arc::new(DelayedOpaqueAes{entered:Default::default(),resume:Default::default(),encrypt_gate:false,decrypt_gate:true});
        let external=CancellationToken::new();let mut c=client();c.set_operation_cancel(external.clone());let c=opaque_client(c,port.clone());let sealed=opaque_sealed(&c);
        let task=tokio::spawn(async move{c.validate_browser_credential_snapshot_async(&sealed).await});
        port.entered.notified().await;external.cancel();port.resume.notify_one();assert!(matches!(task.await.unwrap(),Err(Error::Cancelled)));
    }
    #[tokio::test]
    async fn standalone_opaque_snapshot_preparation_checks_cancel_during_canonical_decrypt_and_seal() {
        for encrypt_gate in [false,true] {
            let email="snapshot-test@example.invalid";let hash=crypto::hash_email(email);
            let account=json!({"user_id":OWNER,"hashed_email":hash,"user_email_salt":"synthetic-salt","encrypted_email_with_master_key":legacy_cipher(email.as_bytes())});
            let (api,peer)=crate::sdk::tests::server(vec![(200,account)]).await;
            let mut c=client();c.base=transport::validate_base(&api).unwrap();c.session.as_mut().unwrap().api_url=api;c.session.as_mut().unwrap().hashed_email=crypto::hash_email(email);
            let external=CancellationToken::new();c.set_operation_cancel(external.clone());
            let port=std::sync::Arc::new(DelayedOpaqueAes{entered:Default::default(),resume:Default::default(),encrypt_gate,decrypt_gate:!encrypt_gate});let mut c=opaque_client(c,port.clone());
            let task=tokio::spawn(async move{c.prepare_browser_credential_snapshot().await});
            port.entered.notified().await;external.cancel();port.resume.notify_one();assert!(matches!(task.await.unwrap(),Err(Error::Cancelled)));assert_eq!(peer.await.unwrap().len(),1);
        }
    }
    #[tokio::test]
    async fn standalone_opaque_validation_accepts_exact_payload_without_cancellation() {
        let port=std::sync::Arc::new(DelayedOpaqueAes{entered:Default::default(),resume:Default::default(),encrypt_gate:false,decrypt_gate:false});
        let c=opaque_client(client(),port);let sealed=opaque_sealed(&c);assert!(c.validate_browser_credential_snapshot_async(&sealed).await.is_ok());assert_eq!(c.credential_ack,0);
    }

}
