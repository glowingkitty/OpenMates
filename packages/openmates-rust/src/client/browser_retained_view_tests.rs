//! Authored UNRUN pure retained projection cases, not admission/browser proof.
// contract-test-file: tooling
use super::*;
const OWNER:&str="11111111-1111-4111-8111-111111111111";
const CHAT:&str="22222222-2222-4222-8222-222222222222";
fn metadata()->Value {json!({"chat_id":CHAT,"user_id":OWNER,"encrypted_chat_key":"synthetic-wrapper-not-used-by-pure-projector",
    "encrypted_title":crypto::encrypt_combined("Actual stored title",&[9;32]).unwrap(),"metadata_v":2,"messages_v":99})}
fn row(physical:&str,logical:&str,at:i64,role:&str,content:&str)->Value {
    json!({"id":physical,"message_id":physical,"client_message_id":logical,"chat_id":CHAT,"created_at":at,"role":role,
        "status":"waiting","queue_revision":9,"queue_dispatch_status":"local-protected",
        "encrypted_content":crypto::encrypt_combined(content,&[9;32]).unwrap(),
        "content":"UNTRUSTED_CLEAR_EXTENSION","unknown_private_extension":{"secret":"NEVER_PROJECT"}})
}
fn dispositions(rows:&[Value])->Vec<Value> {rows.iter().map(|r|json!({"messageId":r["message_id"],"disposition":"retained",
    "incomingSuppliedWriteFieldsMatch":false,"canonicalIncomingDurablyAcknowledged":false})).collect()}
#[test]
fn actual_retained_values_and_logical_aliases_are_projected_without_incoming_authority() {
    let c=Client::new("http://127.0.0.1:9",None).unwrap();let rows=vec![row("physical","logical",1,"user","Actual protected local text")];
    let out=retained_projection(&c,OWNER,CHAT,&metadata(),&rows,&Zeroizing::new([9;32]),&dispositions(&rows),None,None).unwrap();
    assert_eq!(out["source"],"browser_retained_message_cache");assert_eq!(out["chat"]["title"],"Actual stored title");
    assert_eq!(out["chat"]["messages"][0]["id"],"logical");assert_eq!(out["chat"]["messages"][0]["content"],"Actual protected local text");
    assert_eq!(out["messageMetadata"][0]["storageId"],"physical");
    for field in ["historyComplete","fresh","canonicalIncomingDurablyAcknowledged","messagesVersionAdvanced","windowCoverageChanged",
        "credentialAcknowledged","nativeDurabilityAcknowledged","crossDatabaseAssociationProven","inventoryComplete","recoveryProof"] {assert_eq!(out[field],false);}
    for field in ["hasMoreBefore","hasMoreAfter","startCursor","endCursor","checkpointPresentation"]{assert!(out[field].is_null());}
    let encoded=serde_json::to_string(&*out).unwrap();assert!(!encoded.contains("UNTRUSTED_CLEAR_EXTENSION"));assert!(!encoded.contains("NEVER_PROJECT"));
}
#[test]
fn storage_order_uses_existing_utf16_comparator_and_not_server_utf8_order() {
    let c=Client::new("http://127.0.0.1:9",None).unwrap();
    let rows=vec![row("\u{e000}","private-use",1,"assistant","second"),row("\u{10000}","astral",1,"user","first")];
    let out=retained_projection(&c,OWNER,CHAT,&metadata(),&rows,&Zeroizing::new([9;32]),&dispositions(&rows),None,None).unwrap();
    assert_eq!(out["chat"]["messages"][0]["id"],"astral");assert_eq!(out["chat"]["messages"][1]["id"],"private-use");
}
#[test]
fn retained_page_local_pii_uses_only_retained_user_maps() {
    let c=Client::new("http://127.0.0.1:9",None).unwrap();let mut rows=vec![row("u","u",1,"user","[PERSON_1]"),row("a","a",2,"assistant","[PERSON_1] [PERSON_2]")];
    rows[0]["encrypted_pii_mappings"]=json!(crypto::encrypt_combined(&json!([{"placeholder":"[PERSON_1]","original":"Stored user mapping"}]).to_string(),&[9;32]).unwrap());
    rows[1]["encrypted_pii_mappings"]=json!(crypto::encrypt_combined(&json!([{"placeholder":"[PERSON_2]","original":"Assistant map must not apply"}]).to_string(),&[9;32]).unwrap());
    let out=retained_projection(&c,OWNER,CHAT,&metadata(),&rows,&Zeroizing::new([9;32]),&dispositions(&rows),None,None).unwrap();
    assert_eq!(out["chat"]["messages"][1]["content"],"Stored user mapping [PERSON_2]");assert_eq!(out["piiRestoration"],"page_local");
}
#[test]
fn malformed_key_owner_duplicate_alias_or_large_payload_refuses_the_retained_projection() {
    for fault in ["cipher","owner","duplicate","large","dispositions"] {
        let c=Client::new("http://127.0.0.1:9",None).unwrap();let mut meta=metadata();let mut rows=vec![row("p","l",1,"user","stored")];
        match fault {"cipher"=>rows[0]["encrypted_content"]=json!(crypto::encrypt_combined("other key",&[8;32]).unwrap()),
            "owner"=>meta["user_id"]=json!(CHAT),"duplicate"=>rows.push(rows[0].clone()),
            "large"=>rows[0]["large_payload"]=json!({"size_bytes":1,"object_key":"owned-but-unread","checksum":"0".repeat(64)}),_=>{}}
        let ds=if fault=="dispositions"{vec![]}else{dispositions(&rows)};
        assert!(retained_projection(&c,OWNER,CHAT,&meta,&rows,&Zeroizing::new([9;32]),&ds,None,None).is_err(),"{fault}");
    }
}

#[test]
fn extended_cached_dto_keeps_database_logical_stored_and_incoming_physical_ids_distinct(){
 let c=Client::new("http://127.0.0.1:9",None).unwrap();let mut rows=vec![row("stored","logical",1,"assistant","text")];rows[0]["id"]=json!("database");
 let ds=vec![json!({"messageId":"stored","incomingPhysicalMessageId":"incoming","disposition":"retained","incomingSuppliedWriteFieldsMatch":false,"canonicalIncomingDurablyAcknowledged":false})];
 let out=retained_projection(&c,OWNER,CHAT,&metadata(),&rows,&Zeroizing::new([9;32]),&ds,Some("monitor"),None).unwrap();
 assert_eq!(out["chat"]["messages"][0]["id"],"logical");assert_eq!(out["messageMetadata"][0]["storageId"],"database");assert_eq!(out["messageMetadata"][0]["sourceMessageId"],"stored");assert_eq!(out["rowDispositions"][0]["storedPhysicalMessageId"],"stored");assert_eq!(out["rowDispositions"][0]["incomingPhysicalMessageId"],"incoming");assert_eq!(out["cacheReadKind"],"monitor");assert_eq!(out["contentCoverage"],"unknown");assert_eq!(out["canonicalIncomingDurablyAcknowledged"],false);
}
