//! Authored actual shared Rust parser cases, UNRUN. No socket/IDB/owner proof.
use super::*;
fn id(n:u32)->String{format!("{n:08x}-1111-4111-8111-111111111111")}
fn phase2(rows:Vec<Value>)->Value{json!({"chats":rows.into_iter().map(|row|json!({"chat_details":row})).collect::<Vec<_>>()})}
fn terminal(phase:&mut ReadOnlySyncPhase){
    phase.accept("phased_sync_complete",&json!({}),None).unwrap();
    phase.accept("recovery_outputs_discovery_complete",&json!({"status":"disabled"}),None).unwrap();
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
#[test]
fn same_existing_parser_keeps_phase2_arrival_order_child_metadata_and_wrapper_sidecars(){
    let mut read=ReadOnlySyncPhase::new(0).unwrap();
    read.accept("phase_2_last_20_chats_ready",&json!({"chats":[
        {"chat_details":{"id":id(2),"parent_id":id(1),"is_sub_chat":true}},
        {"chat_details":{"id":id(1),"encrypted_title":"cipher"}}],
        "chat_key_wrappers":[{"hashed_chat_id":"synthetic"}],"embeds":[{"embed_id":"synthetic"}],"embed_keys":[{"hashed_embed_id":"synthetic"}]}),None).unwrap();
    assert!(!read.terminal_markers_received());terminal(&mut read);let data=read.finish().unwrap();
    assert_eq!(data.chat_arrival_order,vec![id(2),id(1)]);assert_eq!(data.chats.len(),2);
    assert_eq!(data.chats[&id(2)]["parent_id"],id(1));assert_eq!(data.wrappers.len(),1);assert_eq!(data.embed_keys.len(),1);assert_eq!(data.embeds.len(),1);
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
#[test]
fn original_phase1_keeps_all_metadata_while_content_budget_stays_twenty(){
    let mut read=ReadOnlySyncPhase::new(0).unwrap();let mut parents=(1..=25).map(|n|json!({"id":id(n)})).collect::<Vec<_>>();
    parents.push(json!({"id":id(100),"parent_id":id(1),"is_sub_chat":true}));
    read.accept("phase_1_last_chat_ready",&json!({"context_epoch":0,"team_id":null,"recent_chat_metadata":parents}),None).unwrap();
    read.accept("phase_2_last_20_chats_ready",&phase2(vec![json!({"id":id(100),"parent_id":id(1),"is_sub_chat":true})]),None).unwrap();
    terminal(&mut read);let data=read.finish().unwrap();assert_eq!(data.chats.len(),26);assert!(data.chats.contains_key(&id(20)));assert!(data.chats.contains_key(&id(21)));assert!(data.chats.contains_key(&id(25)));assert!(data.chats.contains_key(&id(100)));
    assert_eq!(data.chat_arrival_order,std::iter::once(id(100)).chain((1..=25).map(id)).collect::<Vec<_>>());
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.authoritative-enforcement
#[test]
fn actual_bounded_content_above20_and_wrong_phase1_context_still_refuse(){
    let rows=(1..=21).map(|n|json!({"chat_id":id(n),"messages":[],"server_message_count":0,"message_window":{"has_more_before":false,"oversized_message":false}})).collect::<Vec<_>>();
    let mut read=ReadOnlySyncPhase::new(0).unwrap();assert!(matches!(read.accept("phase_1b_chat_content_ready",&json!({"context_epoch":0,"team_id":null,"chats":rows}),None),Err(Error::Protocol)));
    let mut read=ReadOnlySyncPhase::new(0).unwrap();assert!(matches!(read.accept("phase_1_last_chat_ready",&json!({"context_epoch":1,"team_id":null,"chat_details":{"id":id(1)}}),None),Err(Error::Forbidden)));
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
#[test]
fn partial_or_malformed_terminal_never_finishes_and_recovery_offers_never_become_effects(){
    let mut read=ReadOnlySyncPhase::new(0).unwrap();read.accept("phase_2_last_20_chats_ready",&phase2(vec![]),None).unwrap();
    read.accept("recovery_jobs_available",&json!({"jobs":[{"chat_id":id(1)}]}),None).unwrap();
    read.accept("recovery_outputs_available",&json!({"outputs":"not consumed by MonitorReadOnly"}),None).unwrap();
    read.accept("phased_sync_complete",&json!({}),None).unwrap();assert!(!read.terminal_markers_received());
    assert!(matches!(read.accept("recovery_outputs_discovery_complete",&json!({"status":"pending"}),None),Err(Error::Protocol)));
    assert!(read.finish().is_err());let mut no_metadata=ReadOnlySyncPhase::new(0).unwrap();terminal(&mut no_metadata);assert!(no_metadata.terminal_markers_received());assert!(no_metadata.finish().is_err());
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
#[test]
fn phase2_wins_overlap_and_bounded_absence_does_not_emit_any_deletion_receipt(){
    let mut read=ReadOnlySyncPhase::new(0).unwrap();read.accept("phase_1_last_chat_ready",&json!({"context_epoch":0,"team_id":null,"chat_details":{"id":id(1),"title_v":1}}),None).unwrap();
    read.accept("phase_2_last_20_chats_ready",&phase2(vec![json!({"id":id(1),"title_v":2})]),None).unwrap();terminal(&mut read);
    assert!(read.accept("phase_2_last_20_chats_ready",&phase2(vec![]),None).is_err());
    let data=read.finish().unwrap();assert_eq!(data.chats[&id(1)]["title_v"],2);assert_eq!(data.chat_arrival_order,vec![id(1)]);
    // This is only received data; no API removes an omitted old Client/IDB row.
    assert_eq!(data.chats.len(),1);
}

// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.authoritative-enforcement
#[test]
fn request_bound_epoch_filters_stale_frames_but_retains_actual_original_connection_marker_data(){
    assert!(ReadOnlySyncPhase::new(9_007_199_254_740_992).is_err());let mut read=ReadOnlySyncPhase::new(23).unwrap();
    read.accept("phase_2_last_20_chats_ready",&json!({"context_epoch":22,"team_id":null,"chats":[{"chat_details":{"id":id(99)}}]}),None).unwrap();
    read.accept("phased_sync_complete",&json!({"context_epoch":22,"team_id":null}),None).unwrap();assert!(!read.terminal_markers_received());
    read.accept("phase_1_last_chat_ready",&json!({"context_epoch":23,"team_id":null,"chat_details":{"id":id(1)}}),None).unwrap();
    read.accept("phase_2_last_20_chats_ready",&json!({"context_epoch":23,"team_id":null,"chats":[]}),None).unwrap();
    // This is the existing original connection's actual validated boundary
    // DATA, not a new correlated/fresh recovery completion or auth grant.
    read.accept("recovery_outputs_discovery_complete",&json!({"status":"disabled"}),None).unwrap();
    read.accept("phased_sync_complete",&json!({"context_epoch":23,"team_id":null}),None).unwrap();assert!(read.terminal_markers_received());
    let data=read.finish().unwrap();assert!(data.chats.contains_key(&id(1)));assert!(!data.chats.contains_key(&id(99)));
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.authoritative-enforcement
#[test]
fn correct_echoed_epoch_is_never_team_scope_or_authority(){
    let mut read=ReadOnlySyncPhase::new(23).unwrap();assert!(matches!(read.accept("phase_2_last_20_chats_ready",&json!({"context_epoch":23,"team_id":id(7),"chats":[]}),None),Err(Error::Forbidden)));
    assert!(read.finish().is_err());
}

fn metadata_page(rows:Vec<Value>,epoch:u64)->Value {
    json!({"chats":rows.into_iter().map(|row|json!({"chat_details":row})).collect::<Vec<_>>(),
        "context_epoch":epoch,"team_id":null,"total_count":1234})
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,sync.startup.bounded-phases,sync.deletion.partial-window-not-authoritative
#[test]
fn expanded_metadata_and_older_pages_keep_distinct_retention_and_original_order(){
    let mut read=ReadOnlySyncPhase::new(0).unwrap();
    read.accept("phase_1_last_chat_ready",&json!({"context_epoch":0,"team_id":null,"recent_chat_metadata":[{"id":id(1),"pinned":true}]}),None).unwrap();
    let child=json!({"id":id(102),"parent_id":id(101),"is_sub_chat":true,"encrypted_title":"opaque雪","encrypted_draft_md":"cipher","draft_v":9,"opaqueUserMetadata":{"camelCase":"😀"}});
    let expanded=metadata_page(vec![json!({"id":id(1),"pinned":false}),json!({"id":id(101),"pinned":true}),child.clone()],0);
    read.accept("sync_metadata_chats_response",&expanded,None).unwrap();read.accept("sync_metadata_chats_response",&expanded,None).unwrap();
    let mut older=metadata_page(vec![json!({"id":id(1001),"parent_id":id(1),"is_sub_chat":true})],0);older["offset"]=json!(1000);older["has_more"]=json!(false);
    read.accept("load_more_chats_response",&older,None).unwrap();read.accept("load_more_chats_response",&older,None).unwrap();
    // Expanded and older EOF are neither startup metadata readiness nor terminals.
    assert!(!read.metadata_seen);assert!(!read.terminal_markers_received());
    read.accept("phase_2_last_20_chats_ready",&phase2(vec![json!({"id":id(2),"draft_v":11})]),None).unwrap();terminal(&mut read);
    let data=read.finish().unwrap();assert_eq!(data.chat_arrival_order,vec![id(2),id(1),id(101),id(102)]);
    assert_eq!(data.chats[&id(102)],child);assert_eq!(data.chats[&id(1)]["pinned"],true);assert!(!data.chats.contains_key(&id(1001)));
    assert_eq!(data.phase1_windows.older_metadata_pages().len(),1);assert_eq!(data.phase1_windows.older_metadata_pages()["1000"],older);
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.authoritative-enforcement
#[test]
fn metadata_responses_filter_epoch_and_team_before_any_sidecar_or_row_ingestion(){
    for kind in ["sync_metadata_chats_response","load_more_chats_response"] {
        let mut read=ReadOnlySyncPhase::new(23).unwrap();let mut page=metadata_page(vec![json!({"id":id(101)})],22);
        page["offset"]=json!(1000);page["has_more"]=json!(false);page["chat_key_wrappers"]=json!([{"untrusted":"ignored"}]);page["embeds"]=json!([{"id":"ignored"}]);
        read.accept(kind,&page,None).unwrap();assert!(read.data.phase1_windows.older_metadata_pages().is_empty());
        page["context_epoch"]=json!(23);page["team_id"]=json!(id(7));assert_eq!(read.accept(kind,&page,None),Err(Error::Forbidden));
        page["team_id"]=Value::Null;read.accept(kind,&page,None).unwrap();
        assert!(read.data.wrappers.is_empty());assert!(read.data.embeds.is_empty());assert!(!read.metadata_seen);
    }
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
#[test]
fn metadata_response_changed_duplicates_and_malformed_pages_are_atomic(){
    let mut read=ReadOnlySyncPhase::new(0).unwrap();let original=metadata_page(vec![json!({"id":id(101),"title_v":1})],0);
    read.accept("sync_metadata_chats_response",&original,None).unwrap();
    let invalid=metadata_page(vec![json!({"id":id(102)}),json!({"id":id(101),"title_v":2})],0);
    assert_eq!(read.accept("sync_metadata_chats_response",&invalid,None),Err(Error::Protocol));
    let mut error=metadata_page(vec![json!({"id":id(103)})],0);error["error"]=json!("failed");read.accept("sync_metadata_chats_response",&error,None).unwrap();
    let mut older=metadata_page(vec![json!({"id":id(1001)})],0);older["offset"]=json!(1000);older["has_more"]=json!(true);
    read.accept("load_more_chats_response",&older,None).unwrap();older["has_more"]=json!(false);assert_eq!(read.accept("load_more_chats_response",&older,None),Err(Error::Protocol));
    let mut malformed=metadata_page(vec![json!({"id":"bad-id"})],0);assert_eq!(read.accept("sync_metadata_chats_response",&malformed,None),Err(Error::Protocol));
    malformed["chats"]=json!([{"id":id(104)}]);assert_eq!(read.accept("sync_metadata_chats_response",&malformed,None),Err(Error::Protocol));
    read.accept("phase_2_last_20_chats_ready",&phase2(vec![]),None).unwrap();terminal(&mut read);let data=read.finish().unwrap();
    assert_eq!(data.chat_arrival_order,vec![id(101)]);assert_eq!(data.chats[&id(101)]["title_v"],1);assert_eq!(data.phase1_windows.older_metadata_pages()["1000"]["has_more"],true);
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
#[test]
fn existing_global_metadata_budget_counts_expanded_and_memory_pages_together(){
    let mut read=ReadOnlySyncPhase::new(0).unwrap();let blob="x".repeat(crate::client::transport::MAX_BODY/2);
    let expanded=metadata_page(vec![json!({"id":id(101),"opaque_extension":blob})],0);read.accept("sync_metadata_chats_response",&expanded,None).unwrap();
    let mut older=metadata_page(vec![json!({"id":id(1001),"opaque_extension":blob})],0);older["offset"]=json!(1000);older["has_more"]=json!(false);
    assert_eq!(read.accept("load_more_chats_response",&older,None),Err(Error::Protocol));assert!(read.data.phase1_windows.older_metadata_pages().is_empty());
    read.accept("phase_2_last_20_chats_ready",&phase2(vec![]),None).unwrap();terminal(&mut read);assert_eq!(read.finish().unwrap().chats.len(),1);
}
// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
#[test]
fn metadata_only_and_older_eof_cannot_finish_without_actual_startup_and_recovery_markers(){
    let mut read=ReadOnlySyncPhase::new(0).unwrap();let mut older=metadata_page(vec![],0);older["offset"]=json!(1000);older["has_more"]=json!(false);
    read.accept("load_more_chats_response",&older,None).unwrap();read.accept("sync_metadata_chats_response",&metadata_page(vec![],0),None).unwrap();terminal(&mut read);
    assert!(read.finish().is_err());
}

// contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,sync.deletion.partial-window-not-authoritative
#[test]
fn fixed_post_startup_metadata_response_requires_real_startup_boundary_and_preserves_startup_precedence(){
    let mut read=ReadOnlySyncPhase::new(0).unwrap();let expanded=metadata_page(vec![json!({"id":id(101),"encrypted_title":"opaque"})],0);
    assert_eq!(read.accept_post_startup_expanded_metadata(&expanded,None),Err(Error::Conflict));
    read.accept("phase_2_last_20_chats_ready",&phase2(vec![json!({"id":id(101),"draft_v":10})]),None).unwrap();terminal(&mut read);
    read.accept_post_startup_expanded_metadata(&expanded,None).unwrap();let data=read.finish().unwrap();assert_eq!(data.chats[&id(101)]["draft_v"],10);assert_eq!(data.chat_arrival_order,vec![id(101)]);
}
