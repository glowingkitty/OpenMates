//! Actual shared AES/owned resources, inert opaque barrier; execution CI-only.
// contract-test-file: tooling
use super::*;
use crate::crypto::master::{MasterCrypto,MasterCryptoFuture};
use super::super::super::super::{credentials,owned_operation::{OwnedOperationScope,ActiveOwnedClient},browser};
use tokio::sync::Notify;
const CHAT:&str="22222222-2222-4222-8222-222222222222";
struct Gate {entered:Notify,release:Notify}
struct AesPort(Arc<Gate>);
impl MasterCrypto for AesPort {
    fn encrypt<'a>(&'a self,iv:&'a [u8;12],bytes:&'a [u8])->MasterCryptoFuture<'a>{Box::pin(async move{crate::crypto::encrypt_aead(bytes,&[7;32],iv,&[]).map(zeroize::Zeroizing::new)})}
    fn decrypt<'a>(&'a self,iv:&'a [u8;12],bytes:&'a [u8])->MasterCryptoFuture<'a>{Box::pin(async move{
        self.0.entered.notify_one();self.0.release.notified().await;
        crate::crypto::decrypt_aead(bytes,&[7;32],iv,&[])
    })}
}
fn client()->Client{
    let api="https://example.invalid";
    let mut c=Client::new(api,Some(Session{api_url:api.into(),session_id:"version-fixture".into(),cookies:BTreeMap::new(),ws_token:None,master_key:zeroize::Zeroizing::new([7;32]),hashed_email:"fixture".into(),user_email_salt:String::new(),email_encryption_key:None,created_at:1,paired_session_expires_at:None,active_team_id:None})).unwrap();
    c.user=json!({"id":"11111111-1111-4111-8111-111111111111"});c
}
fn row(version:u64,key:u8)->Value{json!({"id":CHAT,"messages_v":version,"encrypted_chat_key":crate::crypto::server_fields::encrypt_bytes(&[key;32],&[7;32],&[]).unwrap()})}
fn prepared(c:&Client,source:Value)->PreparedVersionKey{
    prepare_key(c,CHAT,stamp(c,CHAT).unwrap(),Plain::new(source),&c.master_capability().unwrap()).unwrap()
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn exact_server_version_floor_and_original_key_refuse_without_cache_mutation(){
    for (version,key,minimum,expected) in [(3,8,2,true),(1,8,2,false),(3,9,2,false)]{
        let mut c=client();let original=row(2,8);c.insert_chat_row(CHAT.into(),original.clone());
        let completed=prepared(&c,row(version,key)).drive().await;
        let result=commit(&mut c,CHAT,&[8;32],minimum,completed);
        assert_eq!(result.is_ok(),expected);
        if expected{assert_eq!(result.unwrap(),3);assert_eq!(c.chats[CHAT]["messages_v"],3)}else{assert_eq!(c.chats[CHAT],original)}
    }
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn intervening_same_chat_or_wrapper_refuses_without_rollback_but_unrelated_row_survives(){
    for wrapper in [false,true]{
        let mut c=client();c.insert_chat_row(CHAT.into(),row(1,8));let completed=prepared(&c,row(2,8)).drive().await;
        c.chats.insert("unrelated-B".into(),json!({"id":"unrelated-B","messages_v":7}));
        if wrapper{c.wrappers.push(json!({"hashed_chat_id":sha256(CHAT),"key_type":"master","encrypted_chat_key":"newer-actual-wrapper"}))}else{c.chats.get_mut(CHAT).unwrap()["messages_v"]=json!(9)}
        assert!(matches!(commit(&mut c,CHAT,&[8;32],1,completed),Err(Error::Conflict)));
        assert_eq!(c.chats["unrelated-B"]["messages_v"],7);
        if wrapper{assert_eq!(c.wrappers.last().unwrap()["encrypted_chat_key"],"newer-actual-wrapper")}else{assert_eq!(c.chats[CHAT]["messages_v"],9)}
    }
    let mut c=client();c.insert_chat_row(CHAT.into(),row(1,8));let completed=prepared(&c,row(2,8)).drive().await;
    c.chats.insert("unrelated-B".into(),json!({"messages_v":7}));assert_eq!(commit(&mut c,CHAT,&[8;32],1,completed).unwrap(),2);
    assert_eq!(c.chats["unrelated-B"]["messages_v"],7);
}
// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn actual_opaque_unwrap_retains_original_a_until_return_while_b_prepares_and_only_b_cancels(){
    for change in 0..4{
        let gate=Arc::new(Gate{entered:Notify::new(),release:Notify::new()});let mut c=client();
        let mut credentials=credentials::BrowserCredentials::from_native_session(c.session.take().unwrap());
        credentials.master=MasterCapability::opaque_for_test(Arc::new(AesPort(gate.clone())));c.browser_credentials=Some(credentials);
        c.browser_authority=Some(browser::BrowserAuthority{principal:"11111111-1111-4111-8111-111111111111".into(),persistence:browser::BrowserPersistence::MemoryOnly,owner_guards:true});c.browser_local_read_only=false;
        c.insert_chat_row(CHAT.into(),row(1,8));let original=c.chats[CHAT].clone();
        let request=CancellationToken::new();let a=OwnedOperationScope::capture(&c,request.clone()).unwrap();
        let prepared={let active=ActiveOwnedClient::enter(&mut c,&a).unwrap();prepared(&active,row(2,8))};
        let mut decrypt=Box::pin(prepared.drive());
        tokio::select!{biased;_=&mut decrypt=>panic!("must actually await original opaque resource"),_=gate.entered.notified()=>{}}
        // SAME Client is available: genuine fixed B preparation/control uses its
        // own registry child, not an invented bool or replacement Client.
        let b=c.prepare_owned_apps_inventory(CancellationToken::new()).unwrap().unwrap();let b_control=b.control();b_control.cancel();
        assert!(!a.child().is_cancelled());assert!(!request.is_cancelled());
        match change{1=>request.cancel(),2=>c.master_capability().unwrap().invalidate(),3=>c.generation+=1,_=>{}}
        assert!(futures_util::poll!(&mut decrypt).is_pending(),"cancel never fabricates opaque crypto return");
        gate.release.notify_one();let completed=decrypt.await;
        let result={let mut active=ActiveOwnedClient::enter(&mut c,&a);match active.as_mut(){Ok(active)=>commit(active,CHAT,&[8;32],1,completed),Err(_)=>Err(Error::Cancelled)}};
        if change!=0{assert!(result.is_err());assert_eq!(c.chats[CHAT],original)}else{assert_eq!(result.unwrap(),2)}
        drop(b);
    }
}

// contract-test: supporting surface=sdks.rust assertions=sdk.surface.semantic-parity,auth.session.isolation
#[tokio::test]
async fn original_first_wrapper_selection_and_team_cache_replacement_are_preserved(){
    let mut c=client();c.wrappers=vec![json!({"hashed_chat_id":sha256(CHAT),"key_type":"master","encrypted_chat_key":crate::crypto::server_fields::encrypt_bytes(&[8;32],&[7;32],&[]).unwrap()}),json!({"hashed_chat_id":sha256(CHAT),"key_type":"master","encrypted_chat_key":crate::crypto::server_fields::encrypt_bytes(&[9;32],&[7;32],&[]).unwrap()})];
    let completed=prepared(&c,row(3,9)).drive().await;
    assert_eq!(commit(&mut c,CHAT,&[8;32],1,completed).unwrap(),3,"same first wrapper, no new ambiguity policy for reads");
    let completed=prepared(&c,row(4,9)).drive().await;
    c.team_key=Some(("newer-cache".into(),zeroize::Zeroizing::new([6;32])));
    assert!(matches!(commit(&mut c,CHAT,&[8;32],1,completed),Err(Error::Conflict)));
    assert_eq!(c.chats[CHAT]["messages_v"],3);assert_eq!(c.team_key.as_ref().unwrap().1.as_ref(),&[6;32]);
}
