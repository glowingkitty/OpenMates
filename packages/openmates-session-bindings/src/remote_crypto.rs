//! Opaque lifecycle adapter over the existing Core protocol. No crypto algorithms,
//! credentials, profiles, network, state serialization or authority live here.
use crate::BindingError;
use openmates_sdk::{Error, remote_access_crypto::{Envelope, Handshake, HandshakeState, Identity, RemoteSession, Role}};
use std::sync::Mutex;
use zeroize::Zeroizing;
type Result<T> = std::result::Result<T, BindingError>;
fn crypto() -> BindingError { Error::Crypto.into() }
fn conflict() -> BindingError { Error::Conflict.into() }

/// Owns only this adapter's decoded plaintext. Core caller-owned Values retain
/// their public ownership. Reuse the maintained recursive binding wipe policy.
struct WipingRemoteValue {
    value: serde_json::Value,
    #[cfg(test)] probe: Option<std::sync::Arc<Mutex<Vec<bool>>>>,
}
impl WipingRemoteValue {
    fn new(value:serde_json::Value)->Self {Self{value,#[cfg(test)]probe:None}}
    fn encode_with(self,encode:impl FnOnce(&serde_json::Value)->Result<String>)->Result<String> {
        encode(&self.value)
    }
}
impl Drop for WipingRemoteValue {
    fn drop(&mut self) {
        crate::session::wipe_json_value(&mut self.value);
        #[cfg(test)] if let Some(probe)=&self.probe {
            probe.lock().expect("synthetic wipe probe").push(self.value.is_null());
        }
    }
}

/// Single-use Core handshake. No Clone, Debug, Serialize or secret getters.
pub struct RemoteHandshakeHandle { state: Mutex<Option<HandshakeState>> }
impl RemoteHandshakeHandle {
    pub fn new(project_key: &[u8], identity_json: &[u8], role: &str) -> Result<Self> {
        let key = Zeroizing::new(<[u8;32]>::try_from(project_key).map_err(|_|crypto())?);
        let identity = Identity::from_json(identity_json).map_err(BindingError::from)?;
        let role = match role { "requester"=>Role::Requester, "source"=>Role::Source, _=>return Err(crypto()) };
        let state = HandshakeState::new(&key,identity,role).map_err(BindingError::from)?;
        Ok(Self { state: Mutex::new(Some(state)) })
    }
    pub fn handshake_json(&self) -> Result<String> {
        let lock = self.state.try_lock().map_err(|_|conflict())?;
        let state = lock.as_ref().ok_or_else(crypto)?;
        serde_json::to_string(&state.handshake()).map_err(|_|crypto())
    }
    /// Every finish attempt consumes the original pending exchange, including
    /// malformed remote input. No failed authentication can reset/reuse it.
    pub fn finish(&self, remote_json: &[u8]) -> Result<RemoteSessionHandle> {
        let state = self.state.try_lock().map_err(|_|conflict())?.take().ok_or_else(crypto)?;
        let remote = Handshake::from_json(remote_json).map_err(BindingError::from)?;
        let session = state.finish(&remote).map_err(BindingError::from)?;
        Ok(RemoteSessionHandle { state: Mutex::new(Some(session)) })
    }
    pub fn close(&self) -> Result<()> { self.state.try_lock().map_err(|_|conflict())?.take(); Ok(()) }
}
/// Owns the exact uncloneable Core session and its bounded nonce histories.
pub struct RemoteSessionHandle { state: Mutex<Option<RemoteSession>> }
impl RemoteSessionHandle {
    pub fn seal(&self, request_id: &str, plaintext: &[u8]) -> Result<String> {
        let mut lock = self.state.try_lock().map_err(|_|conflict())?;
        let envelope = lock.as_mut().ok_or_else(crypto)?.seal(request_id,plaintext).map_err(BindingError::from)?;
        serde_json::to_string(&envelope).map_err(|_|crypto())
    }
    pub fn open(&self, request_id: &str, envelope_json: &[u8]) -> Result<Zeroizing<Vec<u8>>> {
        let mut lock = self.state.try_lock().map_err(|_|conflict())?;
        let state = lock.as_mut().ok_or_else(crypto)?;
        let envelope = Envelope::from_json(envelope_json).map_err(BindingError::from)?;
        state.open(request_id,&envelope).map_err(BindingError::from)
    }
    /// Core validates JSON before consuming the authenticated nonce. Return
    /// serialized text so foreign Number representations cannot silently alter it.
    pub fn open_json_text(&self, request_id: &str, envelope_json: &[u8]) -> Result<String> {
        let mut lock = self.state.try_lock().map_err(|_|conflict())?;
        let state = lock.as_mut().ok_or_else(crypto)?;
        let envelope = Envelope::from_json(envelope_json).map_err(BindingError::from)?;
        let value = WipingRemoteValue::new(state.open_json(request_id,&envelope).map_err(BindingError::from)?);
        value.encode_with(|value|serde_json::to_string(value).map_err(|_|crypto()))
    }
    pub fn close(&self) -> Result<()> { self.state.try_lock().map_err(|_|conflict())?.take(); Ok(()) }
}

#[cfg(test)]
mod tests {
    use super::*;
    const ID:&[u8]=br#"{"ownerId":"synthetic-owner","projectId":"p","sourceId":"s","sourceSessionId":"a","requestingClientId":"b","keyEpoch":1}"#;
    fn guarded_value()->(WipingRemoteValue,std::sync::Arc<Mutex<Vec<bool>>>) {
        let probe=std::sync::Arc::new(Mutex::new(Vec::new()));
        (WipingRemoteValue{value:serde_json::json!({"synthetic-key":["synthetic-plaintext",{"nested":"private"}]}),probe:Some(probe.clone())},probe)
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn owned_json_value_wipes_on_serialization_success(){
        let(value,probe)=guarded_value();
        let result=value.encode_with(|value|serde_json::to_string(value).map_err(|_|crypto()));
        assert!(result.is_ok());assert_eq!(*probe.lock().expect("synthetic wipe probe"),vec![true]);
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn owned_json_value_wipes_on_serialization_error(){
        let(value,probe)=guarded_value();
        let result=value.encode_with(|_|Err(crypto()));
        assert_eq!(result.err().unwrap().code,"crypto");assert_eq!(*probe.lock().expect("synthetic wipe probe"),vec![true]);
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn owned_json_value_wipes_on_serialization_unwind(){
        let(value,probe)=guarded_value();
        let result=std::panic::catch_unwind(std::panic::AssertUnwindSafe(||value.encode_with(|_|panic!("synthetic encoder unwind"))));
        assert!(result.is_err());assert_eq!(*probe.lock().expect("synthetic wipe probe"),vec![true]);
    }
    fn pair()->(RemoteSessionHandle,RemoteSessionHandle){
        let a=RemoteHandshakeHandle::new(&[7;32],ID,"requester").unwrap_or_else(|_|panic!("synthetic requester"));
        let b=RemoteHandshakeHandle::new(&[7;32],ID,"source").unwrap_or_else(|_|panic!("synthetic source"));
        let ah=a.handshake_json().unwrap_or_else(|_|panic!("synthetic operation"));let bh=b.handshake_json().unwrap_or_else(|_|panic!("synthetic operation"));
        (a.finish(bh.as_bytes()).unwrap_or_else(|_|panic!("synthetic requester finish")),b.finish(ah.as_bytes()).unwrap_or_else(|_|panic!("synthetic source finish")))
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn close_retires_only_the_owned_handshake(){
        let a=RemoteHandshakeHandle::new(&[7;32],ID,"requester").unwrap_or_else(|_|panic!("synthetic admission"));
        let b=RemoteHandshakeHandle::new(&[7;32],ID,"source").unwrap_or_else(|_|panic!("synthetic sibling"));
        a.close().unwrap_or_else(|_|panic!("synthetic operation"));a.close().unwrap_or_else(|_|panic!("synthetic operation"));assert_eq!(a.handshake_json().err().unwrap().code,"crypto");assert!(b.handshake_json().is_ok());
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn malformed_finish_still_consumes_the_original_state(){
        let pending=RemoteHandshakeHandle::new(&[7;32],ID,"requester").unwrap_or_else(|_|panic!("synthetic admission"));
        assert!(pending.finish(b"{").is_err());assert_eq!(pending.handshake_json().err().unwrap().code,"crypto");
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn close_session_does_not_change_sibling_and_json_failure_keeps_nonce(){
        let(a,b)=pair();let malformed=a.seal("r",b"not JSON").unwrap_or_else(|_|panic!("synthetic operation"));
        assert_eq!(b.open_json_text("r",malformed.as_bytes()).err().unwrap().code,"protocol");
        assert_eq!(&*b.open("r",malformed.as_bytes()).unwrap_or_else(|_|panic!("synthetic operation")),b"not JSON");
        assert_eq!(b.open("r",malformed.as_bytes()).err().unwrap().code,"crypto");
        b.close().unwrap_or_else(|_|panic!("synthetic operation"));assert_eq!(b.seal("r",b"x").err().unwrap().code,"crypto");assert!(a.seal("r",b"x").is_ok());
    }
    // contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
    #[test]
    fn json_text_preserves_integer_and_raw_bytes_remain_unmodified(){
        let(a,b)=pair();let plaintext=br#" {"n":9007199254740993} "#;
        let envelope=a.seal("r",plaintext).unwrap_or_else(|_|panic!("synthetic operation"));assert_eq!(b.open_json_text("r",envelope.as_bytes()).unwrap_or_else(|_|panic!("synthetic operation")),"{\"n\":9007199254740993}");
        let envelope=a.seal("r",plaintext).unwrap_or_else(|_|panic!("synthetic operation"));assert_eq!(&*b.open("r",envelope.as_bytes()).unwrap_or_else(|_|panic!("synthetic operation")),plaintext);
    }
}
