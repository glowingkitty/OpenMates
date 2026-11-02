//! Strict JSON framing only. No auth, ownership, key or row selection policy.
//! Validate recursively before serde_json::Value can discard duplicate keys.
//! Serialized message rows undergo the same check before shared normalization.
use super::*;
use serde::de::{DeserializeSeed, Error as _, MapAccess, SeqAccess, Visitor};
use std::{cell::Cell, collections::BTreeSet, fmt};
use zeroize::Zeroize;
const MAX_BYTES: usize = 256 * 1024;
const MAX_DEPTH: usize = 32;
const MAX_NODES: usize = 16384;
#[derive(Eq, PartialEq, Ord, PartialOrd)]
struct Key(String);
impl Drop for Key { fn drop(&mut self) { self.0.zeroize(); } }
impl<'de> serde::Deserialize<'de> for Key {
    fn deserialize<D:serde::Deserializer<'de>>(deserializer:D)->std::result::Result<Self,D::Error> {
        <String as serde::Deserialize>::deserialize(deserializer).map(Key)
    }
}
#[derive(Clone, Copy)]
enum Kind { Json, MessageRows, SerializedRow }
#[derive(Clone, Copy)]
struct Strict<'a> { nodes: &'a Cell<usize>, depth: usize, kind: Kind }
impl Strict<'_> {
    fn child(&self,kind:Kind)->Self { Self{nodes:self.nodes,depth:self.depth+1,kind} }
    fn text<E:serde::de::Error>(&self,value:&str)->std::result::Result<(),E> {
        if matches!(self.kind,Kind::SerializedRow) {
            // The string is a JSON row according to the existing shared reader.
            // Validate its full recursive syntax before any Value conversion.
            let mut decoder=serde_json::Deserializer::from_str(value);
            self.child(Kind::Json).deserialize(&mut decoder).map_err(|_|E::custom("invalid local JSON"))?;
            decoder.end().map_err(|_|E::custom("invalid local JSON"))?;
        }
        Ok(())
    }
}
impl<'de> DeserializeSeed<'de> for Strict<'_> {
    type Value=();
    fn deserialize<D:serde::Deserializer<'de>>(self,decoder:D)->std::result::Result<(),D::Error> {
        let nodes=self.nodes.get().checked_add(1).ok_or_else(||D::Error::custom("local JSON bound"))?;
        if self.depth>MAX_DEPTH||nodes>MAX_NODES {return Err(D::Error::custom("local JSON bound"));}
        self.nodes.set(nodes);decoder.deserialize_any(self)
    }
}
impl<'de> Visitor<'de> for Strict<'_> {
    type Value=();
    fn expecting(&self,f:&mut fmt::Formatter<'_>)->fmt::Result {f.write_str("bounded unique-key JSON")}
    fn visit_bool<E:serde::de::Error>(self,_:bool)->std::result::Result<(),E>{Ok(())}
    fn visit_i64<E:serde::de::Error>(self,_:i64)->std::result::Result<(),E>{Ok(())}
    fn visit_u64<E:serde::de::Error>(self,_:u64)->std::result::Result<(),E>{Ok(())}
    fn visit_f64<E:serde::de::Error>(self,_:f64)->std::result::Result<(),E>{Ok(())}
    fn visit_unit<E:serde::de::Error>(self)->std::result::Result<(),E>{Ok(())}
    fn visit_str<E:serde::de::Error>(self,value:&str)->std::result::Result<(),E>{self.text(value)}
    fn visit_borrowed_str<E:serde::de::Error>(self,value:&'de str)->std::result::Result<(),E>{self.text(value)}
    fn visit_string<E:serde::de::Error>(self,value:String)->std::result::Result<(),E>{
        let value=zeroize::Zeroizing::new(value);self.text(&value)
    }
    fn visit_seq<A:SeqAccess<'de>>(self,mut array:A)->std::result::Result<(),A::Error>{
        let kind=if matches!(self.kind,Kind::MessageRows){Kind::SerializedRow}else{Kind::Json};
        while array.next_element_seed(self.child(kind))?.is_some() {} Ok(())
    }
    fn visit_map<A:MapAccess<'de>>(self,mut object:A)->std::result::Result<(),A::Error>{
        // Each owned decoded key has Drop cleanup, including on duplicate,
        // partial object, nested parse failure or bounded-validation rejection.
        let mut keys=BTreeSet::new();
        while let Some(key)=object.next_key::<Key>()? {
            let kind=if self.depth==0&&key.0=="messages" {Kind::MessageRows}else{Kind::Json};
            if !keys.insert(key) {return Err(A::Error::custom("duplicate local JSON key"));}
            object.next_value_seed(self.child(kind))?;
        }
        Ok(())
    }
}
pub(super) fn validate(encoded:&str)->Result<()> {validate_bounded(encoded,MAX_BYTES)}
// Only the original-native inventory Page/Row parser calls this entrypoint.
pub(super) fn validate_original_draft_inventory(encoded:&str)->Result<()> {validate_bounded(encoded,crate::client::browser::original_draft_bounds::ROW_BYTES)}
// Only the native-proved original physical header path calls this entrypoint.
pub(super) fn validate_original_physical_draft(encoded:&str)->Result<()> {validate_bounded(encoded,crate::client::browser::original_draft_bounds::PACKET_BYTES)}
fn validate_bounded(encoded:&str,max_bytes:usize)->Result<()> {
    if encoded.len()>max_bytes {return Err(Error::Protocol);}
    let nodes=Cell::new(0);let mut decoder=serde_json::Deserializer::from_str(encoded);
    Strict{nodes:&nodes,depth:0,kind:Kind::Json}.deserialize(&mut decoder)?;
    decoder.end()?;Ok(())
}

#[cfg(test)]
mod original_inventory_budget_tests {
    use super::*;
    // contract-test: supporting surface=sdks.rust assertions=auth.secrets.lifecycle,sync.client.shared-rust-policy
    #[test]
    fn original_inventory_accepts_existing_large_draft_without_widening_normal_json(){
        let value=serde_json::json!({"row":{"encrypted_draft_md":"A".repeat(1_400_000)}}).to_string();
        assert!(validate(&value).is_err());assert!(validate_original_draft_inventory(&value).is_ok());
        assert!(validate_original_draft_inventory(&serde_json::json!({"row":"A".repeat(2*1024*1024)}).to_string()).is_err());
    }
    // contract-test: supporting surface=sdks.rust assertions=auth.secrets.lifecycle,sync.client.shared-rust-policy
    #[test]
    fn original_inventory_retains_duplicate_depth_and_nodes_refusal(){
        assert!(validate_original_draft_inventory(r#"{"row":{"draft_v":1,"draft_v":2}}"#).is_err());
        let deep=format!("{}0{}","[".repeat(33),"]".repeat(33));assert!(validate_original_draft_inventory(&deep).is_err());
        let wide=serde_json::json!([vec![0;17000]]).to_string();assert!(validate_original_draft_inventory(&wide).is_err());
    }
}
