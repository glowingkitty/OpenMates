//! Shared existing chat-key selector/Direct policy, split around opaque crypto.
//! No key/auth constructor, replacement Client or new selector is exposed.
use super::*;
use zeroize::Zeroizing;
enum KeyWork {Direct(Key),Wrapped {wrapping:MasterCapability,cipher:Zeroizing<String>}}
pub(in crate::client) struct PreparedChatKey {scope:AsyncCryptoScope,work:KeyWork}
enum KeyResult {Direct(Key),Wrapped(Result<Zeroizing<Vec<u8>>>)}
pub(in crate::client) struct CompletedChatKey {scope:AsyncCryptoScope,result:KeyResult}
impl Client {
    pub(in crate::client) fn prepare_chat_key_with_capability_from(&self,row:&Value,wrapping:&MasterCapability,wrappers:&[Value])->Result<PreparedChatKey>{
        let _=required(row,"id")?;
        let scope=AsyncCryptoScope::begin(self)?;scope.check(self)?;
        let _=self.team()?;
        let work=if text(row,"chat_visibility")=="direct" {
            // Exact existing Direct policy: never export/substitute opaque AES.
            self.native_master_key()?;KeyWork::Direct(self.direct_chat_key(row)?)
        } else {
            let selected=self.chat_key_ciphertext_from(row,false,wrappers)?;
            KeyWork::Wrapped{wrapping:wrapping.clone(),cipher:Zeroizing::new(selected.ciphertext.to_owned())}
        };
        Ok(PreparedChatKey{scope,work})
    }
}
impl PreparedChatKey {
    pub(in crate::client) async fn drive(self)->CompletedChatKey {
        let result=match self.work {
            KeyWork::Direct(key)=>KeyResult::Direct(key),
            KeyWork::Wrapped{wrapping,cipher}=>KeyResult::Wrapped(wrapping.decrypt_bytes(&cipher).await),
        };
        CompletedChatKey{scope:self.scope,result}
    }
}
impl CompletedChatKey {
    pub(in crate::client) fn finish(self,client:&Client)->Result<Key>{
        match self.result {
            KeyResult::Direct(key)=>Ok(key),
            KeyResult::Wrapped(bytes)=>{let bytes=bytes?;self.scope.check(client)?;key_from_bytes(&bytes)}
        }
    }
}
