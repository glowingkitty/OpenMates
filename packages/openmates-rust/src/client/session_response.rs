//! Pure shared normal session response syntax only. These accept untrusted DATA
//! and issue no receipt, principal/credential authority, context or CryptoRoot.
//! Each transport/owner purpose retains its original observations and policy.
use super::*;
pub(in crate::client) fn succeeded(value:&Value)->bool{value.get("success")==Some(&Value::Bool(true))}
pub(in crate::client) fn user(value:&Value)->Result<&Value>{value.get("user").filter(|user|user.is_object()).ok_or(Error::Protocol)}
pub(in crate::client) fn principal(user:&Value)->Result<&str>{
    user.get("id").and_then(Value::as_str).filter(|id|!id.is_empty())
        .or_else(||user.get("user_id").and_then(Value::as_str).filter(|id|!id.is_empty())).ok_or(Error::Protocol)
}
pub(in crate::client) fn websocket_token(value:&Value)->Result<&str>{required(value,"ws_token")}
