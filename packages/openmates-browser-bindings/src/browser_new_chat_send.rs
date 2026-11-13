//! Thin first-request entry to the SAME original portable owned send driver.
//! Rust generates the new UUID/key/metadata through its maintained None path.
//! Typed original updates retain identity DATA, never a native selection grant.
//! Existing full-session/Master/publication, cancel and terminal guards apply.
//! Native canonical persistence remains a separate required step before routing.
use super::*;
use crate::browser::BrowserCoreClient;

#[derive(Default)]
pub(in crate::browser) struct CreationIdentity {chat:String,message:String}
impl CreationIdentity {
    pub(in crate::browser) fn chat_id(&self)->&str{&self.chat}
    pub(in crate::browser) fn matches(&self,chat:&str,message:&str)->bool{!self.chat.is_empty()&&self.chat==chat&&self.message==message}
    pub(in crate::browser) fn observe(&mut self,update:&StreamUpdate)->bool{
        match update {
            StreamUpdate::Started{chat_id,message_id,..}=>{
                if !self.chat.is_empty()||uuid::Uuid::parse_str(chat_id).is_err()||uuid::Uuid::parse_str(message_id).is_err(){return false}
                self.chat=chat_id.clone();self.message=message_id.clone();true
            },
            StreamUpdate::Submitted{chat_id,message_id}|StreamUpdate::Admitted{chat_id,message_id}=>self.matches(chat_id,message_id),
            // Completed identifies the assistant reply, not the user message.
            StreamUpdate::Completed{chat_id,message_id,..}=>!self.chat.is_empty()&&self.chat==*chat_id&&uuid::Uuid::parse_str(message_id).is_ok(),
            StreamUpdate::Content{..}|StreamUpdate::Consent{..}=>!self.chat.is_empty(),
            StreamUpdate::Status(_)=>true,
            StreamUpdate::TaskAssigned{chat_id,message_id,..}=>self.matches(chat_id,message_id),
        }
    }
}
#[wasm_bindgen]
impl BrowserCoreClient {
    pub fn prepare_new_owned_send(&self,handle:&str,generation:f64)->Result<BrowserOwnedPreparedSend,JsValue>{
        let status=self.status(handle,generation)?;
        let prepared=self.client.prepare_owned_saved_send(None,CancellationToken::new()).map_err(|_|JsValue::from_str("session_expired"))?;
        let operation=prepared.id().map_err(|_|JsValue::from_str("session_expired"))?.to_owned();
        let cancel=prepared.cancellation_request().map_err(|_|JsValue::from_str("session_expired"))?;
        let publication=prepared.publication_guard().map_err(|_|JsValue::from_str("session_expired"))?;
        let(sender,receiver)=mpsc::channel(1);
        Ok(BrowserOwnedPreparedSend{state:Rc::new(State{handle:handle.into(),generation,principal:status.principal.clone(),operation,chat_id:String::new(),
            creation:Some(RefCell::new(CreationIdentity::default())),publication,final_publication:RefCell::new(None),cancel,
            finished:Cell::new(false),closed:Cell::new(false),terminal:RefCell::new(None),revoked:Cell::new(false),changed:Notify::new(),receiver:RefCell::new(receiver)}),
            prepared:Some(prepared),sender:Some(sender),receiver_taken:false})
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    const CHAT:&str="22222222-2222-4222-8222-222222222222";
    const USER:&str="33333333-3333-4333-8333-333333333333";
    const REPLY:&str="44444444-4444-4444-8444-444444444444";
    #[test]
    fn original_started_identity_is_one_use_and_completed_reply_may_differ(){
        let mut identity=CreationIdentity::default();
        assert!(identity.observe(&StreamUpdate::Started{chat_id:CHAT.into(),message_id:USER.into(),expects_reply:true}));
        assert!(identity.matches(CHAT,USER));
        assert!(identity.observe(&StreamUpdate::Admitted{chat_id:CHAT.into(),message_id:USER.into()}));
        assert!(identity.observe(&StreamUpdate::Completed{chat_id:CHAT.into(),message_id:REPLY.into(),content:String::new()}));
        assert!(!identity.observe(&StreamUpdate::Started{chat_id:CHAT.into(),message_id:USER.into(),expects_reply:true}));
    }
    #[test]
    fn foreign_chat_user_and_prestarted_content_never_replace_original_identity(){
        let mut identity=CreationIdentity::default();
        assert!(!identity.observe(&StreamUpdate::Content{content:String::new(),thinking:String::new(),mate:String::new()}));
        assert!(!identity.observe(&StreamUpdate::Started{chat_id:"caller".into(),message_id:USER.into(),expects_reply:true}));
        assert!(identity.observe(&StreamUpdate::Started{chat_id:CHAT.into(),message_id:USER.into(),expects_reply:true}));
        assert!(!identity.observe(&StreamUpdate::Admitted{chat_id:REPLY.into(),message_id:USER.into()}));
        assert!(!identity.observe(&StreamUpdate::Submitted{chat_id:CHAT.into(),message_id:REPLY.into()}));
        assert!(identity.matches(CHAT,USER));
    }
}
