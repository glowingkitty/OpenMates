//! Direct reusable Rust opaque-handle library worker for independent test peers.
use _native::{BindingError,RemoteHandshakeHandle,RemoteSessionHandle};
use base64::{Engine as _,engine::general_purpose::URL_SAFE_NO_PAD};
use serde_json::{Value,json};
use std::io::{self,BufRead,Read,Write};
fn protocol()->BindingError {openmates_sdk::Error::Protocol.into()}
fn text<'a>(value:&'a Value,key:&str)->Result<&'a str,BindingError>{value[key].as_str().ok_or_else(protocol)}
fn decoded(value:&Value,key:&str)->Result<Vec<u8>,BindingError>{URL_SAFE_NO_PAD.decode(text(value,key)?).map_err(|_|protocol())}
fn main(){
 let mut pending:Option<RemoteHandshakeHandle>=None;let mut session:Option<RemoteSessionHandle>=None;
 let mut input=io::BufReader::new(io::stdin().lock());let mut output=io::stdout().lock();
 loop{
  let mut line=Vec::new();let n=Read::by_ref(&mut input).take(1024*1024+1).read_until(b'\n',&mut line).unwrap();
  if n==0{break;}if n>1024*1024||line.last()!=Some(&b'\n'){std::process::exit(1);}
  let sequence=serde_json::from_slice::<Value>(&line).ok().and_then(|value|value["sequence"].as_u64());
  let result=(||->Result<Value,BindingError>{
   let item:Value=serde_json::from_slice(&line).map_err(|_|protocol())?;
   let value=match text(&item,"op")?{
    "new"=>{pending=None;session=None;let key=zeroize::Zeroizing::new(decoded(&item,"key")?);let identity=serde_json::to_vec(&item["identity"]).map_err(|_|protocol())?;let handle=RemoteHandshakeHandle::new(&key,&identity,text(&item,"role")?)?;let wire=handle.handshake_json()?;pending=Some(handle);serde_json::from_str(&wire).map_err(|_|protocol())?},
    "handshake"=>serde_json::from_str(&pending.as_ref().ok_or_else(protocol)?.handshake_json()?).map_err(|_|protocol())?,
    "finish"=>{let remote=serde_json::to_vec(&item["remote"]).map_err(|_|protocol())?;session=Some(pending.as_ref().ok_or_else(protocol)?.finish(&remote)?);Value::Null},
    "seal"=>{let plaintext=zeroize::Zeroizing::new(decoded(&item,"plaintext")?);serde_json::from_str(&session.as_ref().ok_or_else(protocol)?.seal(text(&item,"id")?,&plaintext)?).map_err(|_|protocol())?},
    "open"=>{let envelope=serde_json::to_vec(&item["envelope"]).map_err(|_|protocol())?;let plaintext=session.as_ref().ok_or_else(protocol)?.open(text(&item,"id")?,&envelope)?;json!(URL_SAFE_NO_PAD.encode(&plaintext))},
    "open_json_text"=>{let envelope=serde_json::to_vec(&item["envelope"]).map_err(|_|protocol())?;json!(session.as_ref().ok_or_else(protocol)?.open_json_text(text(&item,"id")?,&envelope)?)},
    "close_handshake"=>{pending.as_ref().ok_or_else(protocol)?.close()?;Value::Null},
    "close_session"=>{session.as_ref().ok_or_else(protocol)?.close()?;Value::Null},
    _=>return Err(protocol()),
   };Ok(json!({"ok":true,"value":value}))
  })();
  let mut value=match result{Ok(value)=>value,Err(error)=>json!({"ok":false,"code":error.code})};
  value["sequence"]=json!(sequence);
  serde_json::to_writer(&mut output,&value).unwrap();output.write_all(b"\n").unwrap();output.flush().unwrap();
 }
}
