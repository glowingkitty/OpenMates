//! Supporting selector DATA/resource tests, AUTHORED UNRUN. Synthetic native
//! Session fixtures are not a real server admission or CLI success proof.
use super::*;
const OWNER:&str="11111111-1111-4111-8111-111111111111";
const FIRST:&str="33333333-ffff-4333-8333-333333333333";
const SECOND:&str="33333333-0000-4333-8333-333333333333";
const ALIAS:&str="55555555-5555-4555-8555-555555555555";
fn synthetic_client()->Client{
    let mut client=Client::new("https://api.example.org",Some(Session{
        api_url:"https://api.example.org".into(),session_id:OWNER.into(),cookies:BTreeMap::new(),
        ws_token:Some("synthetic-token".into()),master_key:zeroize::Zeroizing::new([9;32]),
        hashed_email:"synthetic".into(),user_email_salt:String::new(),email_encryption_key:None,
        created_at:1,paired_session_expires_at:None,active_team_id:None,
    })).unwrap();client.user=json!({"id":OWNER,"username":"synthetic"});client
}
fn fixture()->Value{serde_json::from_str(include_str!("../../tests/fixtures/session-saved-embed-selector.json")).unwrap()}
fn rows()->Value{fixture()["payload"].clone()}
fn bind(client:&mut Client)->Arc<SavedEmbedSelectors>{
    let payload=rows();let mut frames=SelectorFrames::default();frames.observe("phase_1b_chat_content_ready",&payload);
    for row in payload["embeds"].as_array().unwrap(){client.embeds.insert(row["embed_id"].as_str().unwrap().into(),row.clone());}
    let original=Arc::new(frames.bind(client).unwrap());client.saved_embed_selectors=Some(original.clone());original
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.isolation
#[test]
fn first_arrival_duplicate_and_both_alias_fields_win_over_sorted_or_latest_map_rows(){
    let mut client=synthetic_client();let original=bind(&mut client);
    assert_eq!(client.embeds.keys().next().unwrap(),SECOND);
    assert_eq!(original.select(&client,"33333333").unwrap(),FIRST);
    assert_eq!(original.select(&client,"55555555").unwrap(),FIRST);
    assert_eq!(original.select(&client,SECOND).unwrap(),SECOND);
    for vector in fixture()["vectors"].as_array().unwrap(){
        assert_eq!(original.select(&client,vector["selector"].as_str().unwrap()).unwrap(),vector["selected"].as_str().unwrap());
    }
    assert!(original.select(&client,"does-not-exist").is_err());
    assert!(original.select(&client,"").is_err());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy
#[test]
fn normal_metadata_unknown_and_sidecar_injection_cannot_create_selector_rows(){
    for kind in ["phase_1_last_chat_ready","phase_2_last_20_chats_ready","sync_metadata_chats_response","load_more_chats_response","unknown"]{
        let mut client=synthetic_client();let mut frames=SelectorFrames::default();frames.observe(kind,&rows());
        let original=frames.bind(&client).unwrap();assert!(original.select(&client,"33333333").is_err());
        client.embeds.insert(FIRST.into(),json!({"embed_id":FIRST}));assert!(original.check(&client).is_err());
    }
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy
#[test]
fn aliases_and_inventory_changes_refuse_but_ciphertext_is_not_mistaken_for_selector_authority(){
    let mut client=synthetic_client();let original=bind(&mut client);
    client.embeds.get_mut(FIRST).unwrap()["encrypted_content"]=json!("opaque replacement");
    assert_eq!(original.select(&client,"33333333").unwrap(),FIRST);
    client.embeds.get_mut(FIRST).unwrap()["id"]=json!(ALIAS);assert!(original.check(&client).is_err());
    let mut client=synthetic_client();let original=bind(&mut client);client.embeds.remove(SECOND);assert!(original.check(&client).is_err());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.encryption.local-only
#[test]
fn original_owner_team_privacy_denial_expiry_cancel_and_forget_remain_negative(){
    for mode in ["owner","team","privacy","denial","expiry","cancel","forget"]{
        let mut client=synthetic_client();let original=bind(&mut client);
        match mode{
            "owner"=>client.user["id"]=json!(ALIAS),
            "team"=>client.session.as_mut().unwrap().active_team_id=Some(ALIAS.into()),
            "privacy"=>client.options.private_operation_gate=Some(Arc::new(||Err(Error::Forbidden))),
            "denial"=>client.task_watch_authority.deny_cached_chat(None).unwrap(),
            "expiry"=>client.session.as_mut().unwrap().paired_session_expires_at=Some(1),
            "cancel"=>client.operation_cancel.cancel(),
            "forget"=>client.forget_session(),_=>unreachable!(),
        }
        assert!(original.select(&client,"33333333").is_err(),"{mode}");
        if mode=="forget"{assert!(client.saved_embed_selectors.is_none());}
    }
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.isolation
#[test]
fn bounded_or_malformed_roster_never_falls_back_to_map_order(){
    let client=synthetic_client();let mut malformed=SelectorFrames::default();malformed.observe("phase_1b_chat_content_ready",&json!({"embeds":[{"embed_id":42}]}));assert!(malformed.bind(&client).is_err());
    let mut bounded=SelectorFrames::default();let row=json!({"embeds":[{"embed_id":FIRST}]});
    for _ in 0..=MAX_ROWS{bounded.observe("background_message_sync",&row);}
    assert!(bounded.disabled);assert!(bounded.rows.is_empty());assert!(bounded.bind(&client).is_err());
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.isolation
#[tokio::test]
async fn restored_or_missing_roster_refuses_public_read_before_auth_or_socket_io(){
    let mut client=synthetic_client();assert!(matches!(client.saved_embed_selector("33333333").await,Err(Error::Unavailable{code:"saved_embed_selector_order_unavailable",..})));
    bind(&mut client);let snapshot=client.ciphertext_snapshot();assert!(snapshot.get("saved_embed_selectors").is_none());
    client.restore_ciphertext_snapshot(&snapshot).unwrap();assert!(client.saved_embed_selectors.is_none());
    assert!(matches!(client.saved_embed_selector(FIRST).await,Err(Error::Unavailable{code:"saved_embed_selector_order_unavailable",..})));
}

// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.isolation
#[test]
fn native_order_cache_decision_never_forces_an_ambiguous_or_legacy_refresh(){
    assert_eq!(SelectorCache::Absent.decision(1,true).unwrap(),CacheDecision::Sync);
    assert!(SelectorCache::Legacy.decision(1,true).is_err());
    let known=SelectorCache::Ordered{at:1,owner:OWNER.into(),frames:SelectorFrames::default(),identities:BTreeMap::new()};
    assert_eq!(known.decision(60_000,false).unwrap(),CacheDecision::Reuse);
    assert!(known.decision(60_001,true).is_err());
    assert!(known.decision(300_001,false).is_err());
    assert_eq!(known.decision(300_001,true).unwrap(),CacheDecision::Sync);
    assert!(known.decision(0,true).is_err());
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.isolation
#[tokio::test]
async fn authenticated_order_roundtrip_rebinds_data_only_and_ordinary_snapshot_cannot(){
    let mut live=synthetic_client();bind(&mut live);let mut frames=SelectorFrames::default();frames.observe("phase_1b_chat_content_ready",&rows());
    live.saved_embed_cache=SelectorCache::Ordered{at:now_ms(),owner:OWNER.into(),frames,identities:live.saved_embed_selectors.as_ref().unwrap().identities.clone()};
    let snapshot=live.ciphertext_snapshot();assert!(snapshot.get(CACHE_FIELD).is_some());
    let mut ordinary=synthetic_client();ordinary.restore_ciphertext_snapshot(&snapshot).unwrap();assert!(matches!(ordinary.saved_embed_cache,SelectorCache::Legacy));
    assert!(ordinary.ensure_saved_embed_selector().await.is_err());
    let mut restored=synthetic_client();restored.restore_authenticated_ciphertext_snapshot(&snapshot).unwrap();assert!(restored.saved_embed_selectors.is_none());
    restored.ensure_saved_embed_selector().await.unwrap();assert_eq!(restored.saved_embed_selectors.as_ref().unwrap().select(&restored,"55555555").unwrap(),FIRST);
    restored.embeds.remove(SECOND);assert!(restored.saved_embed_selectors.as_ref().unwrap().check(&restored).is_err());
}
// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.encryption.local-only
#[test]
fn malformed_optional_order_preserves_legacy_data_and_never_mints_order(){
    for value in [json!(null),json!({"version":2,"synced_at":1,"rows":[]}),json!({"version":1,"synced_at":1,"rows":[{"embed_id":42,"id":null}]}),json!({"version":1,"synced_at":1,"rows":[],"fresh":true})]{
        assert!(matches!(SelectorCache::restore(Some(&value),true),SelectorCache::Legacy));
    }
}

// contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sync.client.shared-rust-policy
#[tokio::test]
async fn authenticated_cache_owner_alias_addition_removal_and_cancel_are_still_negative(){
    let mut live=synthetic_client();bind(&mut live);let mut frames=SelectorFrames::default();frames.observe("phase_1b_chat_content_ready",&rows());
    live.saved_embed_cache=SelectorCache::Ordered{at:now_ms(),owner:OWNER.into(),frames,identities:live.saved_embed_selectors.as_ref().unwrap().identities.clone()};
    let snapshot=live.ciphertext_snapshot();
    for mode in ["owner","alias","add","remove","cancel"]{
        let mut c=synthetic_client();c.restore_authenticated_ciphertext_snapshot(&snapshot).unwrap();
        match mode{
            "owner"=>c.user["id"]=json!(ALIAS),
            "alias"=>c.embeds.get_mut(FIRST).unwrap()["id"]=json!(ALIAS),
            "add"=>{c.embeds.insert(ALIAS.into(),json!({"embed_id":ALIAS}));},
            "remove"=>{c.embeds.remove(SECOND);},
            "cancel"=>c.operation_cancel.cancel(),_=>unreachable!(),
        }
        assert!(c.ensure_saved_embed_selector().await.is_err(),"{mode}");
    }
}

// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.isolation
#[test]
fn genuine_unsynced_empty_native_persist_is_distinct_from_old_or_untrusted_cache(){
    let client=synthetic_client();let snapshot=client.ciphertext_snapshot();assert_eq!(snapshot[CACHE_FIELD],json!({"version":1,"state":"unsynced"}));
    let mut authenticated=synthetic_client();authenticated.restore_authenticated_ciphertext_snapshot(&snapshot).unwrap();assert!(matches!(authenticated.saved_embed_cache,SelectorCache::Absent));
    let mut ordinary=synthetic_client();ordinary.restore_ciphertext_snapshot(&snapshot).unwrap();assert!(matches!(ordinary.saved_embed_cache,SelectorCache::Legacy));
    let mut missing=snapshot.clone();missing.as_object_mut().unwrap().remove(CACHE_FIELD);let mut old=synthetic_client();old.restore_authenticated_ciphertext_snapshot(&missing).unwrap();assert!(matches!(old.saved_embed_cache,SelectorCache::Legacy));
    let mut contradiction=snapshot.clone();contradiction["embeds"]=json!({FIRST:{"embed_id":FIRST}});let mut mixed=synthetic_client();mixed.restore_authenticated_ciphertext_snapshot(&contradiction).unwrap();assert!(matches!(mixed.saved_embed_cache,SelectorCache::Legacy));
    for value in [json!({"version":1,"state":"unsynced","fresh":true}),json!({"version":1,"state":"unsynced","rows":[]}),json!({"version":2,"state":"unsynced"})]{assert!(matches!(SelectorCache::restore(Some(&value),true),SelectorCache::Legacy));}
}
