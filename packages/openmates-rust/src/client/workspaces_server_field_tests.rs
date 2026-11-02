//! Actual native Client mutations and draft-to-chat wrapper wire compatibility.
//! Synthetic loopback peers only; no deployed browser or account proof.
// contract-test: supporting surface=cli assertions=chats.messages.client-encrypted
use super::*;
use base64::{Engine as _,engine::general_purpose::STANDARD};
use tokio::io::{AsyncReadExt,AsyncWriteExt};
pub(in crate::client) fn strict_legacy(ciphertext:&str,key:&[u8;32])->zeroize::Zeroizing<Vec<u8>> {
    let bytes=STANDARD.decode(ciphertext).unwrap();assert!(bytes.len()>=28);
    let plain=crypto::decrypt_aead(&bytes[12..],key,&bytes[..12],&[]).unwrap();assert_eq!(bytes.len(),12+plain.len()+16);
    let mut tampered=bytes.clone();*tampered.last_mut().unwrap()^=1;
    assert!(crypto::decrypt_aead(&tampered[12..],key,&tampered[..12],&[]).is_err());
    assert!(crypto::decrypt_aead(&bytes[12..],&[99;32],&bytes[..12],&[]).is_err());plain
}
pub(super) async fn peer(singular:&'static str)->(String,tokio::task::JoinHandle<Value>){
    let listener=tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();let base=format!("http://{}",listener.local_addr().unwrap());
    let task=tokio::spawn(async move {
        let(mut stream,_)=listener.accept().await.unwrap();let mut bytes=vec![];let mut chunk=[0;4096];
        let end=loop{let n=stream.read(&mut chunk).await.unwrap();assert!(n>0);bytes.extend_from_slice(&chunk[..n]);if let Some(i)=bytes.windows(4).position(|w|w==b"\r\n\r\n"){break i+4;}};
        let headers=String::from_utf8(bytes[..end].to_vec()).unwrap();assert!(headers.starts_with(if singular=="task"{"POST /v1/user-tasks"}else{"POST /v1/projects"}));
        let length=headers.lines().find_map(|l|l.to_ascii_lowercase().strip_prefix("content-length:").map(|v|v.trim().parse::<usize>().unwrap())).unwrap();
        while bytes.len()<end+length{let n=stream.read(&mut chunk).await.unwrap();assert!(n>0);bytes.extend_from_slice(&chunk[..n]);}
        let body:Value=serde_json::from_slice(&bytes[end..end+length]).unwrap();let response=json!({(singular):body.clone()}).to_string();
        stream.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{response}",response.len()).as_bytes()).await.unwrap();body
    });(base,task)
}
#[tokio::test]
async fn actual_personal_and_team_task_project_create_fields_are_legacy_compatible(){
    let fixtures:Value=serde_json::from_str(include_str!("../../tests/fixtures/native-workspace-server-fields.json")).unwrap();assert_eq!(fixtures["cases"].as_array().unwrap().len(),4);
    for case in fixtures["cases"].as_array().unwrap(){
        let task=case["workspace"]=="Tasks";let team=case["team"].as_bool().unwrap();let workspace=if task{Workspace::Tasks}else{Workspace::Projects};
        let(base,peer)=peer(if task{"task"}else{"project"}).await;let mut c=super::delete_tests::client(&base,team,false);
        if team{c.team_key=Some(("22222222-2222-4222-8222-222222222222".into(),zeroize::Zeroizing::new([7;32])));}
        let mut fields=json!({"title":"Synthetic private title","description":"Synthetic private description","slug":"synthetic-private-slug"});
        if !task{fields["default_focus_id"]=json!("33333333-3333-4333-8333-333333333333");fields["write_mode"]=json!("always_ask");fields["settings"]=json!({"private":"synthetic setting"});}
        // Call the actual shared headless mutation, not a wire reconstruction.
        let result=c.mutate(Mutation::Create{workspace,fields}).await.unwrap().unwrap();assert_eq!(result.title,"Synthetic private title");let body=peer.await.unwrap();
        let key_field=case["key_field"].as_str().unwrap();let key=key_from_bytes(&strict_legacy(body[key_field].as_str().unwrap(),&[7;32])).unwrap();assert_ne!(*key,[7;32]);
        for field in case["encrypted_fields"].as_array().unwrap(){let field=field.as_str().unwrap();let plain=strict_legacy(body[field].as_str().unwrap(),&key);assert!(!plain.is_empty());}
        assert_eq!(&*strict_legacy(body["encrypted_slug"].as_str().unwrap(),&key),b"synthetic-private-slug");
        assert_eq!(body["slug_lookup_hash"],crypto::object_slug_lookup_hash("synthetic-private-slug",&[7;32]).unwrap());
        if team{assert_eq!(body["key_wrappers"][0]["key_type"],"team");assert_eq!(body["key_wrappers"][0][key_field],body[key_field]);assert_eq!(body["key_wrappers"][0]["team_key_epoch"],1);}
        let wire=body.to_string();for secret in ["Synthetic private title","Synthetic private description","synthetic-private-slug","synthetic setting"]{assert!(!wire.contains(secret));}
    }
}
