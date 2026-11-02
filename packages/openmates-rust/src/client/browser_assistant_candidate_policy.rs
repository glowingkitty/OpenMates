//! Maintained duplicate/decryption-failure policy only; never grants delete authority.
use super::*;
#[derive(Default)]
pub(super) struct Failures(BTreeMap<String,std::collections::BTreeSet<String>>);
impl Failures {
 pub(super) fn clear(&mut self,chat:Option<&str>){if let Some(chat)=chat.filter(|s|!s.is_empty()){self.0.remove(chat);}else{self.0.clear();}}
 pub(super) fn known(&self,chat:&str,message:&str,field:&str,fp:Option<&str>)->bool {
  let Some(entries)=self.0.get(chat)else{return false};let prefix=format!("{message}:{field}");
  if let Some(fp)=fp.filter(|s|!s.is_empty()){entries.contains(&format!("{prefix}:{fp}"))}else{entries.iter().any(|v|v==&prefix||v.starts_with(&format!("{prefix}:")))}
 }
 pub(super) fn record(&mut self,chat:&str,message:&str,field:&str,fp:Option<&str>){let prefix=format!("{message}:{field}");let key=fp.filter(|s|!s.is_empty()).map(|fp|format!("{prefix}:{fp}")).unwrap_or(prefix);self.0.entry(chat.into()).or_default().insert(key);}
}
// EXACT maintained comparison fingerprint; never authentication or key authority.
fn fingerprint(key:&[u8;32])->String {let mut a=0x811c9dc5u32;for v in key {a=(a^u32::from(*v)).wrapping_mul(0x01000193);}let mut b=0x1a47e90bu32;for v in key.iter().rev(){b=(b^u32::from(*v)).wrapping_mul(0x01000193);}format!("{a:08x}{b:08x}")}
// Exact maintained base64ToUint8Array preprocessing + forgiving atob decoding.
// This browser-candidate-only adapter never changes native/default decoding.
fn browser_cipher_bytes(encoded:&str)->Result<Zeroizing<Vec<u8>>> {
 if encoded.is_empty(){return Err(Error::Crypto)}
 let mut value=Zeroizing::new(encoded.replace('-',"+").replace('_',"/"));
 let remainder=value.len()%4;if remainder!=0{value.push_str(&"=".repeat(4-remainder));}
 let mut input=Zeroizing::new(value.bytes().filter(|b|!matches!(b,9|10|12|13|32)).collect::<Vec<_>>());
 if input.len()%4==0 {for _ in 0..2{if input.last()==Some(&b'='){input.pop();}else{break}}}
 if input.len()%4==1{return Err(Error::Crypto)}
 let mut out=Zeroizing::new(Vec::new());let mut acc=0u32;let mut bits=0u32;
 for &c in input.iter(){let sextet=match c{b'A'..=b'Z'=>c-b'A',b'a'..=b'z'=>c-b'a'+26,b'0'..=b'9'=>c-b'0'+52,b'+'=>62,b'/'=>63,_=>return Err(Error::Crypto)};acc=(acc<<6)|u32::from(sextet);bits+=6;if bits>=8{bits-=8;out.push((acc>>bits)as u8);acc&=(1u32<<bits)-1;}}
 Ok(out)
}
pub(super) fn browser_decrypt(row:&Value,cipher:&str,key:&Key)->Result<String>{
 use base64::Engine;
 let encoded=required(row,cipher)?;let bytes=browser_cipher_bytes(encoded)?;
 let canonical=Zeroizing::new(base64::engine::general_purpose::STANDARD.encode(&*bytes));
 // Reuse the maintained shared framed/legacy AES-GCM decoder after input-only
 // browser normalization, preserving original wire spelling in returned rows.
 let mut scratch=Plain::new(json!({}));scratch[cipher]=json!(&*canonical);
 sync::decrypt_optional(&scratch,cipher,key)
}
/// Owns the ORIGINAL full derived-key identity; weak comparison fingerprints
/// never allow failures to leak into another key namespace. Drop wipes key.
#[derive(Clone,Copy)]pub(super) enum ReadMode {Connected,Disconnected,WebSocketError,ForcedLogout}
pub(super) struct KeyFailures {key:Key,fp:String,failures:Failures}
impl KeyFailures {
 pub(super) fn new(key:&Key)->Self{Self{key:key.clone(),fp:fingerprint(key),failures:Failures::default()}}
 pub(super) fn same_key(&self,key:&Key)->bool {self.key.as_ref()==key.as_ref()}
 pub(super) fn clear(&mut self){self.failures.clear(None);}
 /// Caller must hold the ORIGINAL monitor context + Fence. This pure projection
 /// is not a socket-health proof and is never used by generic HTTP replacement.
 pub(super) fn project(&mut self,row:&Value,chat:&str,mode:ReadMode)->Result<Plain<Value>> {
  let message=required(row,"message_id")?;if row["chat_id"]!=chat{return Err(Error::Forbidden)}
  let mut out=Plain::new(row.clone());if matches!(mode,ReadMode::WebSocketError|ReadMode::ForcedLogout){return Ok(out)}
  for (cipher,field) in ENCRYPTED.iter().zip(CLEAR.iter()) {
   let Some(value)=row.get(*cipher).filter(|v|!v.is_null())else{continue};
   let encoded=value.as_str().ok_or(Error::Protocol)?;if encoded.is_empty(){continue}
   // Actual optional PII syntax guard removes malformed ciphertext instead of
   // recording a permanent crypto failure.
   if *field=="pii_mappings" {
    let well_formed=browser_cipher_bytes(encoded).is_ok_and(|v|v.len()>=29);
    if !well_formed {out.as_object_mut().ok_or(Error::Protocol)?.remove(*cipher);out.as_object_mut().unwrap().remove(*field);continue}
   }
   let plain=if self.failures.known(chat,message,field,Some(&self.fp)){None}else{
    match browser_decrypt(row,cipher,&self.key){Ok(plain)if !plain.is_empty()=>Some(Zeroizing::new(plain)),_=>{self.failures.record(chat,message,field,Some(&self.fp));None}}
   };
   if let Some(plain)=plain {
    if *field=="pii_mappings" {match serde_json::from_str::<Value>(&plain){Ok(parsed)=>{let parsed=Plain::new(parsed);out[*field]=parsed.into_inner();},Err(_)=>{self.failures.record(chat,message,field,Some(&self.fp));out.as_object_mut().unwrap().remove(*field);continue;}}}else{out[*field]=json!(&*plain)}
    if *field=="thinking_content"{out["has_thinking"]=json!(true)}
    out.as_object_mut().ok_or(Error::Protocol)?.remove(*cipher);
   } else {
    let fallback=match *field {"content"=>Some("[Content decryption failed]"),"sender_name"=>Some("Unknown"),_=>None};
    if matches!(*field,"content"|"sender_name"|"category"|"model_name")&&row.get(*field).is_some_and(|v|v.as_str().is_some_and(|s|!s.is_empty())){out[*field]=row[*field].clone();}
    else if let Some(value)=fallback{out[*field]=json!(value)}else{out.as_object_mut().ok_or(Error::Protocol)?.remove(*field);}
   }
  }
  // JS explicitly sets undefined when an assistant has no encrypted model and
  // no plaintext model; JSON-shaped projection omits that property.
  if row["role"]=="assistant"&&row.get("encrypted_model_name").is_none_or(|v|v.is_null()||v.as_str()==Some(""))&&out.get("model_name").is_none_or(|v|v.is_null()||v.as_str()==Some("")){out.as_object_mut().unwrap().remove("model_name");}
  Ok(out)
 }
}
pub(super) fn content_duplicate(old:&Value,new:&Value)->Result<bool> {
 if old["chat_id"]!=new["chat_id"]||old["role"]!=new["role"]{return Ok(false)}
 if old["role"]=="user"&&old["message_id"]!=new["message_id"]{return Ok(false)}
 let cipher=old["encrypted_content"].as_str().filter(|v|!v.is_empty()).zip(new["encrypted_content"].as_str().filter(|v|!v.is_empty()));
 let same_content=if let Some((a,b))=cipher {a==b}else{old["content"].as_str().filter(|v|!v.is_empty()).zip(new["content"].as_str().filter(|v|!v.is_empty())).is_some_and(|(a,b)|a==b)};
 let a=safe_number(&old["created_at"])?;let b=safe_number(&new["created_at"])?;
 let assistant=old["role"]=="assistant";let sender=assistant||old.get("encrypted_sender_name")==new.get("encrypted_sender_name");
 Ok(same_content&&a.abs_diff(b)<if assistant{60}else{300}&&sender)
}
#[derive(Debug,PartialEq,Eq)]pub(super) enum Selection {NoDuplicate,Retain(usize),Replace(usize)}
/// Input is the actual maintained index order (created_at then UTF16 physical
/// primary key). Returning Replace is POLICY ONLY; no storage/delete authority.
pub(super) fn select(candidates:&[Value],incoming:&Value)->Result<Selection> {
 for (index,old) in candidates.iter().enumerate(){if old["message_id"]==incoming["message_id"]{continue}if content_duplicate(old,incoming)?{return Ok(if message_policy::should_update_message(old,incoming)?{Selection::Replace(index)}else{Selection::Retain(index)})}}
 Ok(Selection::NoDuplicate)
}

#[cfg(test)]mod tests {
 use super::*;
 fn fixture()->Value{serde_json::from_str(include_str!("../../tests/fixtures/browser-assistant-candidate-policy.json")).unwrap()}
 #[test]fn actual_browser_base64_primitive_vectors(){for case in fixture()["browser_base64"].as_array().unwrap(){let actual=browser_cipher_bytes(case["input"].as_str().unwrap());if case["bytes"].is_null(){assert!(actual.is_err(),"{}",case["input"]);}else{let expected:Vec<u8>=case["bytes"].as_array().unwrap().iter().map(|v|v.as_u64().unwrap()as u8).collect();assert_eq!(&*actual.unwrap(),&expected,"{}",case["input"]);}}}
 #[test]fn actual_maintained_weak_fingerprint_vectors(){for case in fixture()["key_fingerprints"].as_array().unwrap(){let bytes:Vec<u8>=case["bytes"].as_array().unwrap().iter().map(|v|v.as_u64().unwrap() as u8).collect();let key:[u8;32]=bytes.try_into().unwrap();assert_eq!(fingerprint(&key),case["expected"].as_str().unwrap());}}
 #[test]fn actual_shared_failure_sequences(){for case in fixture()["failure_sequences"].as_array().unwrap(){let mut cache=Failures::default();for (index,step) in case["steps"].as_array().unwrap().iter().enumerate(){let args=step.as_array().unwrap();let s=|i|args.get(i).and_then(Value::as_str);match s(0).unwrap(){"clear"=>cache.clear(s(1)),"record"=>cache.record(s(1).unwrap(),s(2).unwrap(),s(3).unwrap(),s(4)),"known"=>assert_eq!(cache.known(s(1).unwrap(),s(2).unwrap(),s(3).unwrap(),s(4)),case["expected"][index].as_bool().unwrap(),"{}",case["id"]),_=>panic!("unknown fixed fixture operation")}}}}
 #[test]fn actual_shared_selection_vectors(){for case in fixture()["selection_cases"].as_array().unwrap(){let result=select(case["candidates"].as_array().unwrap(),&case["incoming"]).unwrap();let actual=match result{Selection::NoDuplicate=>json!({"kind":"no_duplicate"}),Selection::Retain(index)=>json!({"kind":"retain","index":index}),Selection::Replace(index)=>json!({"kind":"replace","index":index})};assert_eq!(actual,case["expected"],"{}",case["id"]);}}
 fn row(cipher:String)->Value{json!({"message_id":"opaque / id:content","chat_id":"chat","role":"assistant","status":"delivered","created_at":1,"encrypted_content":cipher})}
 #[test]fn healthy_and_disconnected_decrypt_error_logout_keep_raw_without_recording(){let key=Zeroizing::new([9;32]);for mode in [ReadMode::Connected,ReadMode::Disconnected,ReadMode::WebSocketError,ReadMode::ForcedLogout]{let mut cache=KeyFailures::new(&key);let raw=row(crypto::encrypt_combined("text",&key).unwrap());let actual=cache.project(&raw,"chat",mode).unwrap();if matches!(mode,ReadMode::Connected|ReadMode::Disconnected){assert_eq!(actual["content"],"text");assert!(actual.get("encrypted_content").is_none());}else{assert_eq!(*actual,raw);assert!(!cache.failures.known("chat","opaque / id:content","content",Some(&cache.fp)));}}}
 #[test]fn empty_failure_stays_in_original_full_key_namespace_and_key_reload_clears(){let key=Zeroizing::new([9;32]);let mut cache=KeyFailures::new(&key);let bad=row(crypto::encrypt_combined("",&key).unwrap());let actual=cache.project(&bad,"chat",ReadMode::Connected).unwrap();assert_eq!(actual["content"],"[Content decryption failed]");assert!(actual.get("encrypted_content").is_some());let good=row(crypto::encrypt_combined("later valid",&key).unwrap());assert_eq!(cache.project(&good,"chat",ReadMode::Connected).unwrap()["content"],"[Content decryption failed]");let other=Zeroizing::new([8;32]);assert!(!cache.same_key(&other));cache.clear();assert_eq!(cache.project(&good,"chat",ReadMode::Connected).unwrap()["content"],"later valid");}
 #[test]fn malformed_pii_guard_and_invalid_json_follow_distinct_failure_paths(){let key=Zeroizing::new([9;32]);let mut cache=KeyFailures::new(&key);let mut raw=row(crypto::encrypt_combined("text",&key).unwrap());raw["encrypted_pii_mappings"]=json!("malformed");let projected=cache.project(&raw,"chat",ReadMode::Connected).unwrap();assert!(projected.get("encrypted_pii_mappings").is_none());assert!(!cache.failures.known("chat","opaque / id:content","pii_mappings",Some(&cache.fp)));raw["encrypted_pii_mappings"]=json!(crypto::encrypt_combined("not-json",&key).unwrap());let projected=cache.project(&raw,"chat",ReadMode::Connected).unwrap();assert!(projected.get("encrypted_pii_mappings").is_some());assert!(projected.get("pii_mappings").is_none());assert!(cache.failures.known("chat","opaque / id:content","pii_mappings",Some(&cache.fp)));}
}
