//! Pure opaque-only merge. Construction alone confers no origin or IO authority.
use super::*;
const MAX_SAFE: u64 = 9_007_199_254_740_991;
// Pure derivation only: this never constructs native/authenticated authority.
// The sole production caller supplies the configured string retained inside
// NativeMetadataContext and still checks that original resource around IO.
pub(super) fn configured_endpoint(api:&str,path:&str)->Result<url::Url> {
    if !matches!(path,"/v1/auth/session"|"/v1/chats/metadata/batch"){return Err(Error::Forbidden)}
    url::Url::parse(&format!("{api}{path}")).map_err(|_|Error::Protocol)
}
const CIPHERS:&[&str]=&["encrypted_title","encrypted_category","encrypted_icon","encrypted_chat_summary","encrypted_share_cta_text","encrypted_chat_tags","encrypted_follow_up_request_suggestions","encrypted_suggested_followup_message","encrypted_active_focus_id","encrypted_focus_phase_state","encrypted_auto_speak_response","encrypted_chat_key","anonymous_encrypted_chat_key"];
const CLOCKS:&[&str]=&["messages_v","title_v","metadata_v","created_at","updated_at","last_edited_overall_timestamp","unread_count","ideabucket_triggered_at"];
fn validate_source(source:&Value)->Result<()> {
    if !source.is_object(){return Err(Error::Protocol)}
    // Validate the ACTUAL source before legacy truthiness/defaulting can turn
    // false/0 into null/zero and erase an already stored cipher or clock.
    for field in CIPHERS {if source.get(*field).is_some_and(|v|!v.is_null()&&!v.is_string()){return Err(Error::Protocol)}}
    for field in CLOCKS {clock(source,field)?;}
    for field in ["pinned","is_shared","is_private","is_anonymous","share_pii","share_highlights"] {if source.get(field).is_some_and(|v|!v.is_null()&&!v.is_boolean()){return Err(Error::Protocol)}}
    Ok(())
}
/// The existing metadata/batch HTTP watch projection deliberately stringifies
/// timestamps. The already deployed opt-in read_details carries the same
/// authorized row's original values; use exactly that canonical source rather
/// than guessing/coercing watch strings into clocks. Construction is DATA only.
pub(super) fn http_source(row:&Value)->Result<Plain<Value>> {
    let details=row.get("read_details").and_then(Value::as_object).ok_or(Error::Unavailable{code:"chat_details_projection_unavailable",reason:"The server does not provide the selected rich-read projection."})?;
    let mut source=Plain::new(row.clone());
    for field in ["created_at","updated_at","last_edited_overall_timestamp","encrypted_follow_up_request_suggestions"] {
        let value=details.get(field).ok_or(Error::Protocol)?;
        source[field]=value.clone();
    }
    source.as_object_mut().ok_or(Error::Protocol)?.remove("read_details");
    validate_source(&source)?;Ok(source)
}
fn canonical_id(id: &str) -> bool { uuid::Uuid::parse_str(id).is_ok_and(|v|v.to_string()==id) }
fn personal(row:&Value, chat:&str, owner:&str, physical:bool)->Result<()> {
    if !row.is_object() || !canonical_id(chat) {return Err(Error::Protocol)}
    if physical && row.get("chat_id").and_then(Value::as_str)!=Some(chat) {return Err(Error::Forbidden)}
    if row.get("id").filter(|v|!v.is_null()).is_some_and(|v|v.as_str()!=Some(chat)) ||
       row.get("chat_id").filter(|v|!v.is_null()).is_some_and(|v|v.as_str()!=Some(chat)) ||
       row.get("user_id").filter(|v|!v.is_null()).is_some_and(|v|v.as_str()!=Some(owner)) {return Err(Error::Forbidden)}
    for field in ["team_id","hashed_team_id","parent_chat_id","parent_id"] {
        if row.get(field).is_some_and(|v|!v.is_null()&&v.as_str()!=Some("")){return Err(Error::Forbidden)}
    }
    for field in ["is_sub_chat","is_hidden","is_hidden_candidate","is_shared","is_anonymous"] {
        if row.get(field).is_some_and(|v|!v.is_null()&&v!=false){return Err(Error::Forbidden)}
    }
    if row.get("chat_visibility").is_some_and(|v|!v.is_null()&&!matches!(v.as_str(),Some(""|"personal"))){return Err(Error::Forbidden)}
    Ok(())
}
#[derive(Clone,Copy)]
enum RowKind { Parent, Subchat }
// Child navigation DATA has the same Personal/owner boundary, but it is not a
// top-level parent. No parent row, key, content or access permission is inferred.
fn personal_subchat_record(row:&Value,chat:&str,owner:&str,physical:bool)->Result<()> {
    if !row.is_object()||!canonical_id(chat){return Err(Error::Protocol)}
    if physical&&row.get("chat_id").and_then(Value::as_str)!=Some(chat){return Err(Error::Forbidden)}
    if row.get("id").filter(|v|!v.is_null()).is_some_and(|v|v.as_str()!=Some(chat))||row.get("chat_id").filter(|v|!v.is_null()).is_some_and(|v|v.as_str()!=Some(chat))||row.get("user_id").filter(|v|!v.is_null()).is_some_and(|v|v.as_str()!=Some(owner)){return Err(Error::Forbidden)}
    for field in ["team_id","hashed_team_id"]{if row.get(field).is_some_and(|v|!v.is_null()&&v.as_str()!=Some("")){return Err(Error::Forbidden)}}
    for field in ["is_shared","is_anonymous"]{if row.get(field).is_some_and(|v|!v.is_null()&&v!=false){return Err(Error::Forbidden)}}
    if row.get("chat_visibility").is_some_and(|v|!v.is_null()&&!matches!(v.as_str(),Some(""|"personal"))){return Err(Error::Forbidden)}
    for field in ["is_sub_chat","is_hidden","is_hidden_candidate"]{if row.get(field).is_some_and(|v|!v.is_null()&&!v.is_boolean()){return Err(Error::Protocol)}}
    Ok(())
}
/// Restricting DATA extraction only; only the driver's actual authenticated
/// child response can construct its private captured-source resource.
pub(super) fn subchat_parent<'a>(source:&'a Value,chat:&str,owner:&str)->Result<&'a str> {
    validate_source(source)?;personal_subchat_record(source,chat,owner,false)?;
    if source["id"].as_str()!=Some(chat)||source["is_sub_chat"]!=true{return Err(Error::Forbidden)}
    let parent=source["parent_id"].as_str().filter(|id|canonical_id(id)&&*id!=chat).ok_or(Error::Protocol)?;
    Ok(parent)
}
fn clock(row:&Value,name:&str)->Result<Option<u64>> {
    row.get(name).filter(|v|!v.is_null()).map(|v|v.as_u64().filter(|v|*v<=MAX_SAFE).ok_or(Error::Protocol)).transpose()
}
pub(super) fn merge(source:&Value,before:&Value,chat:&str,owner:&str,now:u64)->Result<Plain<Value>> {
    merge_kind(source,before,chat,owner,now,RowKind::Parent)
}
/// Navigation-only child metadata. Parent identity is always from actual source
/// DATA, never a method argument; a link grants no parent access or content.
pub(super) fn merge_subchat(source:&Value,before:&Value,chat:&str,owner:&str,now:u64)->Result<Plain<Value>> {
    let parent=subchat_parent(source,chat,owner)?;
    let mut after=merge_kind(source,before,chat,owner,now,RowKind::Subchat)?;
    after["parent_id"]=json!(parent);after["is_sub_chat"]=json!(true);
    for field in ["is_hidden","is_hidden_candidate"] {
        if let Some(value)=source.get(field).filter(|v|!v.is_null()){after[field]=value.clone();}
    }
    Ok(after)
}
fn merge_kind(source:&Value,before:&Value,chat:&str,owner:&str,now:u64,kind:RowKind)->Result<Plain<Value>> {
    validate_source(source)?;
    match kind {RowKind::Parent=>personal(source,chat,owner,false)?,RowKind::Subchat=>{subchat_parent(source,chat,owner)?;}}
    if source.get("id").and_then(Value::as_str)!=Some(chat){return Err(Error::Forbidden)}
    // A server wrapped key remains opaque. This path never unwraps or generates one.
    if !source.get("encrypted_chat_key").is_some_and(|v|v.as_str().is_some_and(|v|!v.is_empty())) {return Err(Error::Unavailable{code:"metadata_bootstrap_key_missing",reason:"SERVER_OPAQUE_WRAPPED_KEY_REQUIRED"})}
    if !before.is_null(){match kind{RowKind::Parent=>personal(before,chat,owner,true)?,RowKind::Subchat=>personal_subchat_record(before,chat,owner,true)?,}}
    let mut built=super::header::build(source,(!before.is_null()).then_some(before),now)?;
    for field in ["messages_v","title_v","metadata_v","created_at","updated_at","last_edited_overall_timestamp","unread_count"] {clock(&built,field)?;}
    for(field,value)in built.as_object().ok_or(Error::Protocol)? {
        if field.starts_with("encrypted_") && !value.is_null() && !value.is_string(){return Err(Error::Protocol)}
    }
    super::header::validate_create(&built,chat,owner)?;
    if before.is_null(){return Ok(built)}
    for field in ["draft_v","cleared_draft_v"] {clock(before,field)?;}
    for field in ["encrypted_draft_md","encrypted_draft_preview"] {
        if before.get(field).is_some_and(|v|!v.is_null()&&!v.is_string()){return Err(Error::Protocol)}
    }
    if before.get("is_metadata_only")==Some(&Value::Bool(false)) || before.get("messages").is_some() || before.get("title").is_some_and(|v|!v.is_null()) {return Err(Error::Conflict)}
    // Source omission must not erase already-present opaque metadata.
    for(name,value)in before.as_object().ok_or(Error::Protocol)? {
        if name.starts_with("encrypted_")&&!name.starts_with("encrypted_draft_")&&source.get(name).is_none()&&built.get(name).is_some(){built[name]=value.clone();}
    }
    super::header::validate_create(&built,chat,owner)?;
    // Existing full/keyed headers stay under their existing cache policy. This
    // narrow facet repairs only genuinely partial keyless physical rows.
    if before.get("encrypted_chat_key").is_some_and(|v|!v.is_null()&&v.as_str()!=Some("")) {
        return Err(Error::Unavailable{code:"metadata_bootstrap_existing_header",reason:"EXISTING_HEADER_POLICY_REQUIRED"})
    }
    for field in ["title_v","metadata_v"] {clock(before,field)?;}
    // EXACT maintained version policy: aggregate stale-envelope floor plus
    // independent nondecrease for each present revision; null/omitted revisions
    // are not writes. Authenticated canonical cipher rewrap is legitimate even
    // at the same revision. No new same-cipher/equal-timestamp rule is invented.
    drop(super::super::patch(source,before)?);
    for field in ["updated_at","last_edited_overall_timestamp"] {
        if let Some(old)=clock(before,field)? {
            let new=clock(&built,field)?.ok_or(Error::Conflict)?;
            if new<old{return Err(Error::Conflict)}
        }
    }
    // Start from the ENTIRE original physical row: retain unknown extensions,
    // draft ciphers/clear floors and exact field absence, including id:null.
    let mut after=Plain::new(before.clone());
    for(name,value)in built.as_object_mut().ok_or(Error::Protocol)? {
        if matches!(name.as_str(),"draft_v"|"encrypted_draft_md"|"encrypted_draft_preview"|"title"|"processing_metadata"|"waiting_for_metadata"|"is_metadata_only") {continue}
        if matches!(name.as_str(),"title_v"|"metadata_v")&&source.get(name).is_none_or(Value::is_null){continue}
        after[name]=value.take();
    }
    after["is_metadata_only"]=json!(true);
    // Do not assert local processing completion when a real local flag exists.
    for name in ["title","processing_metadata","waiting_for_metadata"] {if before.get(name).is_none(){after[name]=built[name].clone();}}
    Ok(after)
}
#[cfg(test)]mod tests {
 use super::*;
 const C:&str="11111111-1111-4111-8111-111111111111";const O:&str="22222222-2222-4222-8222-222222222222";
 fn source()->Value{json!({"id":C,"encrypted_chat_key":"opaque","encrypted_title":"cipher","metadata_v":2,"title_v":2,"updated_at":2})}
 #[test]fn absent_opaque_header_has_no_plaintext_or_messages(){let v=merge(&source(),&Value::Null,C,O,3).unwrap();assert_eq!(v["encrypted_chat_key"],"opaque");assert_eq!(v["title"],Value::Null);assert!(v.get("messages").is_none());assert_eq!(v["is_metadata_only"],true);}
 #[test]fn clear_floor_and_unknown_fields_survive_exactly(){let b=json!({"chat_id":C,"id":null,"draft_v":9,"cleared_draft_v":9,"encrypted_draft_md":null,"custom":{"nested":[1,null]},"processing_metadata":true});let v=merge(&source(),&b,C,O,3).unwrap();for k in ["id","draft_v","cleared_draft_v","encrypted_draft_md","custom","processing_metadata"]{assert_eq!(v[k],b[k]);}assert!(v.get("encrypted_draft_preview").is_none());}
 #[test]fn cipher_draft_retained_without_decrypt(){let b=json!({"chat_id":C,"draft_v":8,"encrypted_draft_md":"not-decrypted","encrypted_draft_preview":"opaque"});let v=merge(&source(),&b,C,O,3).unwrap();assert_eq!(v["encrypted_draft_md"],b["encrypted_draft_md"]);assert_eq!(v["draft_v"],8);}
 #[test]fn foreign_newer_keyed_and_subchat_refuse(){for b in [json!({"chat_id":O}),json!({"chat_id":C,"user_id":C}),json!({"chat_id":C,"metadata_v":3}),json!({"chat_id":C,"encrypted_chat_key":"old"}),json!({"chat_id":C,"parent_id":O})]{assert!(merge(&source(),&b,C,O,3).is_err());}let mut s=source();s["team_id"]=json!(O);assert!(merge(&s,&Value::Null,C,O,3).is_err());}
}

#[cfg(test)]mod additional_tests {
 use super::*;
 const C:&str="11111111-1111-4111-8111-111111111111";const O:&str="22222222-2222-4222-8222-222222222222";
 fn source()->Value{json!({"id":C,"encrypted_chat_key":"opaque","encrypted_title":"new","title_v":2,"metadata_v":2,"updated_at":2})}
 #[test]fn no_scalar_or_malformed_source_can_upgrade_opaque_merge(){for s in [Value::Null,json!(true),json!({"id":C}),json!({"id":O,"encrypted_chat_key":"opaque"}),json!({"id":C,"encrypted_chat_key":"opaque","encrypted_title":true}),json!({"id":C,"encrypted_chat_key":"opaque","metadata_v":9007199254740992u64})]{assert!(merge(&s,&Value::Null,C,O,3).is_err());}}
 #[test]fn omitted_cipher_preserved_and_authenticated_same_revision_rewrap_allowed(){let b=json!({"chat_id":C,"encrypted_icon":"local","title_v":1});let a=merge(&source(),&b,C,O,3).unwrap();assert_eq!(a["encrypted_icon"],"local");let b=json!({"chat_id":C,"encrypted_title":"different","title_v":2});assert_eq!(merge(&source(),&b,C,O,3).unwrap()["encrypted_title"],"new");}
 #[test]fn existing_full_or_bad_draft_remains_under_original_policy(){for b in [json!({"chat_id":C,"is_metadata_only":false}),json!({"chat_id":C,"messages":[]}),json!({"chat_id":C,"title":"existing-plaintext"}),json!({"chat_id":C,"draft_v":"bad"}),json!({"chat_id":C,"encrypted_draft_md":true})]{assert!(merge(&source(),&b,C,O,3).is_err());}}
}

#[cfg(test)]mod review_regression_tests {
 use super::*;
 const C:&str="11111111-1111-4111-8111-111111111111";const O:&str="22222222-2222-4222-8222-222222222222";
 fn source()->Value{json!({"id":C,"encrypted_chat_key":"opaque","encrypted_title":"new","title_v":2,"metadata_v":2,"updated_at":2})}
 #[test]fn configured_endpoints_keep_lan_prefix_and_literal_slashes(){for api in ["http://192.168.1.100:8000","https://selfhost.example/custom/api","https://selfhost.example/custom/api/"]{for path in ["/v1/auth/session","/v1/chats/metadata/batch"]{assert_eq!(configured_endpoint(api,path).unwrap().as_str(),format!("{api}{path}"));}}assert!(configured_endpoint("https://configured.example","/v1/auth/logout").is_err());}
 #[test]fn malformed_truthy_and_falsey_ciphers_never_erase_local_cipher(){let before=json!({"chat_id":C,"encrypted_title":"old","title_v":1,"metadata_v":1});for value in [json!(false),json!(0),json!(true),json!(1),json!([]),json!({})]{let mut s=source();s["encrypted_title"]=value;assert!(merge(&s,&before,C,O,3).is_err());}let mut s=source();s["encrypted_title"]=Value::Null;assert_eq!(merge(&s,&before,C,O,3).unwrap()["encrypted_title"],Value::Null);}
 #[test]fn false_clock_does_not_become_zero(){for field in CLOCKS {let mut s=source();s[*field]=json!(false);assert!(merge(&s,&Value::Null,C,O,3).is_err());}let mut s=source();s["title_v"]=json!(0);assert!(merge(&s,&Value::Null,C,O,3).is_ok());}
 #[test]fn actual_http_watch_timestamps_use_only_raw_read_details(){let mut row=source();row["created_at"]=json!("1");row["updated_at"]=json!("2");row["last_edited_overall_timestamp"]=json!("2");row["read_details"]=json!({"created_at":1,"updated_at":2,"last_edited_overall_timestamp":2,"encrypted_follow_up_request_suggestions":null});let s=http_source(&row).unwrap();let after=merge(&s,&Value::Null,C,O,3).unwrap();assert_eq!(after["created_at"],1);assert_eq!(after["updated_at"],2);assert!(s.get("read_details").is_none());row.as_object_mut().unwrap().remove("read_details");assert!(http_source(&row).is_err());}
}

#[cfg(test)]mod revision_compatibility_tests {
 use super::*;
 const C:&str="11111111-1111-4111-8111-111111111111";const O:&str="22222222-2222-4222-8222-222222222222";
 fn source()->Value{json!({"id":C,"encrypted_chat_key":"opaque","encrypted_title":"new","title_v":2,"metadata_v":2,"updated_at":2,"last_edited_overall_timestamp":2})}
 #[test]fn actual_source_newer_revisions_same_second_follow_existing_patch_policy(){let before=json!({"chat_id":C,"encrypted_title":"old","title_v":1,"metadata_v":1,"updated_at":2,"last_edited_overall_timestamp":2});let after=merge(&source(),&before,C,O,3).unwrap();assert_eq!(after["encrypted_title"],"new");assert_eq!(after["title_v"],2);assert_eq!(after["metadata_v"],2);assert_eq!(after["updated_at"],2);}
 #[test]fn older_independent_revisions_and_timestamp_floors_still_refuse(){for before in [json!({"chat_id":C,"title_v":3,"metadata_v":1}),json!({"chat_id":C,"title_v":1,"metadata_v":3}),json!({"chat_id":C,"updated_at":3}),json!({"chat_id":C,"last_edited_overall_timestamp":3})]{assert!(merge(&source(),&before,C,O,3).is_err());}let before=json!({"chat_id":C,"title_v":1,"metadata_v":3});let mut source=source();source["title_v"]=json!(4);assert!(merge(&source,&before,C,O,3).is_err());}
 #[test]fn null_revision_does_not_erase_existing_floor_and_same_revision_rewrap_is_canonical(){let before=json!({"chat_id":C,"encrypted_title":"rewrapped-old","title_v":1,"metadata_v":1});let mut source=source();source["metadata_v"]=Value::Null;let after=merge(&source,&before,C,O,3).unwrap();assert_eq!(after["metadata_v"],1);assert_eq!(after["title_v"],2);source["metadata_v"]=json!(1);source["title_v"]=json!(1);assert_eq!(merge(&source,&before,C,O,3).unwrap()["encrypted_title"],"new");}
}

#[cfg(test)]
#[path="browser_metadata_subchat_tests.rs"]
mod subchat_tests;

// Startup uses actual same-socket per-row source and actual native owner/CAS.
// This pure function alone never constructs either authority or an ACK.
pub(super) fn merge_startup(source:&Value,before:&Value,chat:&str,owner:&str,team:Option<&str>,expanded_only:bool,now:u64)->Result<Plain<Value>> {
    validate_source(source)?;startup_scope(source,chat,owner,team,false)?;
    if source["id"].as_str()!=Some(chat){return Err(Error::Forbidden)}
    if !before.is_null(){startup_scope(before,chat,owner,team,true)?;validate_source(before)?;}
    for row in [source,before] {for field in ["draft_v","cleared_draft_v"]{clock(row,field)?;}for field in ["encrypted_draft_md","encrypted_draft_preview"]{if row.get(field).is_some_and(|v|!v.is_null()&&!v.is_string()){return Err(Error::Protocol)}}}
    // Match existing expanded batchSaveMetadataChats: full physical rows keep
    // their own content policy. A received page is not permission to replace it.
    let metadata_only=before.get("is_metadata_only")==Some(&Value::Bool(true));
    let keyed=["encrypted_chat_key","anonymous_encrypted_chat_key"].iter().any(|field|before.get(*field).is_some_and(|v|v.as_str().is_some_and(|s|!s.is_empty())));
    let full=!before.is_null()&&(before["is_metadata_only"]==false||before.get("messages").is_some()||before.get("title").is_some_and(|v|!v.is_null())||(!metadata_only&&keyed));
    // Deployed batchSaveMetadataChats preserves every existing non-metadata-only
    // row, including legacy absent/null flags and separate message storage.
    if expanded_only&&!before.is_null()&&!metadata_only{return Ok(Plain::new(before.clone()))}
    if !before.is_null(){
        drop(super::super::patch(source,before)?);
        for field in ["updated_at","last_edited_overall_timestamp"] {if let(Some(old),Some(new))=(clock(before,field)?,clock(source,field)?){if new<old{return Err(Error::Conflict)}}}
    }
    let mut after=if before.is_null(){super::header::build(source,None,now)?}else{Plain::new(before.clone())};
    // Preserve complete existing physical rows, omitted fields, local flags,
    // message content/counts and unknown extensions. Never publish plaintext
    // from server metadata or turn content availability into a metadata flag.
    for(name,value)in source.as_object().ok_or(Error::Protocol)? {
        if matches!(name.as_str(),"id"|"chat_id"|"team_id"|"title"|"messages"|"history"|"embeds"|"embed_keys"|"chat_key_wrappers"|"draft_v"|"cleared_draft_v"|"encrypted_draft_md"|"encrypted_draft_preview"|"processing_metadata"|"waiting_for_metadata"|"is_metadata_only"){continue}
        if name=="messages_v"&&full{continue}
        // No same-key or explicit mismatch-recovery witness exists here. Keep
        // the actual existing wrapped key; differing strings can be legitimate
        // rewraps and are not a reason to reject otherwise canonical metadata.
        // Incoming wrappers stay retained in the original source batch.
        if matches!(name.as_str(),"encrypted_chat_key"|"anonymous_encrypted_chat_key")&&!before.is_null()
            &&(before.get(name).is_some_and(|v|v.as_str().is_some_and(|s|!s.is_empty()))||value.is_null()||value.as_str()==Some("")){continue}
        if matches!(name.as_str(),"title_v"|"metadata_v")&&value.is_null(){continue}
        if name.starts_with("encrypted_")&&!value.is_null()&&!value.is_string(){return Err(Error::Protocol)}
        after[name]=value.clone();
    }
    after["chat_id"]=json!(chat);after["team_id"]=team.map_or(Value::Null,|id|json!(id));
    if !before.is_null()&&!full&&!metadata_only{after["is_metadata_only"]=json!(true);}
    // All child navigation fields come from the actual row, with no parent fetch
    // or implied access, content slot or crypto-root upgrade.
    if let Some(parent)=source.get("parent_id").filter(|v|!v.is_null()&&v.as_str()!=Some("")) {after["parent_id"]=parent.clone();after["is_sub_chat"]=json!(true);}
    merge_startup_draft(source,before,&mut after)?;
    Ok(after)
}
fn startup_scope(row:&Value,chat:&str,owner:&str,team:Option<&str>,physical:bool)->Result<()> {
    if !row.is_object()||!canonical_id(chat)||!canonical_id(owner){return Err(Error::Protocol)}
    if physical&&row["chat_id"].as_str()!=Some(chat){return Err(Error::Forbidden)}
    // Explicit null is Personal; a missing legacy physical scope is unknown.
    // Neither may be relabelled as Team by a metadata write. Fresh rows are
    // admitted only through the actual source's captured Team context.
    if physical&&team.is_some()&&row.get("team_id").and_then(Value::as_str)!=team{return Err(Error::Forbidden)}
    for field in ["id","chat_id"]{if row.get(field).is_some_and(|v|!v.is_null()&&v.as_str()!=Some(chat)){return Err(Error::Forbidden)}}
    if let Some(value)=row.get("team_id").filter(|v|!v.is_null()&&v.as_str()!=Some("")){let actual=value.as_str().filter(|id|canonical_id(id)).ok_or(Error::Protocol)?;if Some(actual)!=team{return Err(Error::Forbidden)}}
    for field in ["user_id","hashed_team_id"]{if row.get(field).is_some_and(|v|!v.is_null()&&!v.is_string()){return Err(Error::Protocol)}}
    if team.is_none(){
        if row.get("hashed_team_id").is_some_and(|v|!v.is_null()&&v.as_str()!=Some("")){return Err(Error::Forbidden)}
        if row.get("user_id").is_some_and(|v|!v.is_null()&&v.as_str()!=Some(owner)){return Err(Error::Forbidden)}
    }
    if let Some(parent)=row.get("parent_id").filter(|v|!v.is_null()&&v.as_str()!=Some("")){if !parent.as_str().is_some_and(|id|canonical_id(id)&&id!=chat){return Err(Error::Protocol)}}
    if row["is_sub_chat"]==true&&!row.get("parent_id").and_then(Value::as_str).is_some_and(canonical_id){return Err(Error::Protocol)}
    for field in ["is_sub_chat","is_hidden","is_hidden_candidate","is_metadata_only"]{if row.get(field).is_some_and(|v|!v.is_null()&&!v.is_boolean()){return Err(Error::Protocol)}}
    // Existing physical plaintext/local data remains untouched. Server sources
    // in this capability are encrypted metadata, never private content/keys.
    if !physical {for field in ["title","content","draft_md","messages","history","master_key","cookies","ws_token","auth_refresh_token"]{if row.get(field).is_some_and(|v|!v.is_null()){return Err(Error::Protocol)}}}
    Ok(())
}
fn merge_startup_draft(source:&Value,before:&Value,after:&mut Value)->Result<()> {
    let Some(version)=clock(source,"draft_v")? else{return Ok(())};
    let old=clock(before,"draft_v")?.unwrap_or(0);let clear=clock(before,"cleared_draft_v")?.unwrap_or(0);
    let incoming_clear=clock(source,"cleared_draft_v")?.unwrap_or(0);let floor=old.max(clear);
    match source.get("encrypted_draft_md") {
        Some(Value::String(cipher)) if !cipher.is_empty()&&version>clear.max(incoming_clear)&&version>=old=>{
            after["draft_v"]=json!(version);after["encrypted_draft_md"]=json!(cipher);
            if let Some(preview)=source.get("encrypted_draft_preview"){after["encrypted_draft_preview"]=preview.clone();}
            if incoming_clear>clear{after["cleared_draft_v"]=json!(incoming_clear);}
        },
        Some(Value::Null) if version.max(incoming_clear)>=floor=>{
            after["draft_v"]=json!(version);after["encrypted_draft_md"]=Value::Null;after["encrypted_draft_preview"]=Value::Null;
            let retained=floor.max(version).max(incoming_clear);if retained>0||before.get("cleared_draft_v").is_some(){after["cleared_draft_v"]=json!(retained);}
        },
        _=>{}, // Omission/older envelope never deletes a newer local/clear floor.
    }
    Ok(())
}
// Pure metadata projection only, not a source/read/write/retirement grant.
// The caller must have the original recovery and actual native full-row proof.
pub(super) fn merge_recovered_metadata(source:&Value,before:&Value,chat:&str,owner:&str)->Result<Plain<Value>>{
    validate_source(source)?;validate_source(before)?;
    startup_scope(source,chat,owner,None,false)?;startup_scope(before,chat,owner,None,true)?;
    let patch=super::super::patch(source,before)?;let mut after=Plain::new(before.clone());
    for(field,value)in patch.as_object().ok_or(Error::Protocol)?{after[field]=value.clone();}Ok(after)
}

#[cfg(test)]mod recovery_metadata_merge_tests {
 use super::*;
 const C:&str="11111111-1111-4111-8111-111111111111";const O:&str="22222222-2222-4222-8222-222222222222";
 // contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,chats.persistence.client-encrypted
 #[test]fn recovery_canonical_metadata_preserves_actual_keys_drafts_content_and_unknown_fields(){
  let before=json!({"chat_id":C,"user_id":O,"team_id":null,"encrypted_chat_key":"original-wrap","anonymous_encrypted_chat_key":"original-anonymous","metadata_v":2,"title_v":2,"messages_v":7,"draft_v":9,"encrypted_draft_md":"actual-draft","processing_metadata":true,"messages":[{"opaque":"preserved"}],"custom":{"nil":null}});
  let source=json!({"id":C,"user_id":O,"team_id":null,"encrypted_chat_key":"legitimate-rewrap","metadata_v":3,"title_v":3,"encrypted_title":"canonical-title","encrypted_chat_summary":"canonical-summary","messages_v":99,"draft_v":10,"encrypted_draft_md":"not-a-draft-source","unknownServerField":"not-a-write"});
  let after=merge_recovered_metadata(&source,&before,C,O).unwrap();
  for field in ["encrypted_chat_key","anonymous_encrypted_chat_key","messages_v","draft_v","encrypted_draft_md","processing_metadata","messages","custom"]{assert_eq!(after[field],before[field]);}
  assert_eq!(after["metadata_v"],3);assert_eq!(after["title_v"],3);assert_eq!(after["encrypted_title"],"canonical-title");assert!(after.get("unknownServerField").is_none());
 }
 // contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.isolation
 #[test]fn recovered_metadata_independent_rollback_foreign_scope_and_plaintext_never_replace_existing(){
  let before=json!({"chat_id":C,"team_id":null,"encrypted_chat_key":"original","title_v":9,"metadata_v":2,"custom":[null]});
  for source in [json!({"id":C,"title_v":8,"metadata_v":100}),json!({"id":C,"title_v":10,"metadata_v":1}),json!({"id":C,"title_v":10,"metadata_v":3,"team_id":O}),json!({"id":C,"title_v":10,"metadata_v":3,"user_id":C}),json!({"id":C,"title_v":10,"metadata_v":3,"title":"plaintext"})]{assert!(merge_recovered_metadata(&source,&before,C,O).is_err());assert_eq!(before["encrypted_chat_key"],"original");assert_eq!(before["custom"],json!([null]));}
 }
}

#[cfg(test)]mod startup_retention_tests {
 use super::*;
 const C:&str="11111111-1111-4111-8111-111111111111";const O:&str="22222222-2222-4222-8222-222222222222";const P:&str="33333333-3333-4333-8333-333333333333";const T:&str="44444444-4444-4444-8444-444444444444";
 fn source()->Value{json!({"id":C,"encrypted_chat_key":"wrapped","encrypted_title":"server","title_v":2,"metadata_v":2,"messages_v":99,"updated_at":2,"pinned":true,"opaqueUserMetadata":{"camelCase":["雪","😀"]}})}
 // contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,sync.startup.bounded-phases
 #[test]fn startup_fresh_metadata_keeps_all_received_fields_and_child_navigation_without_content(){let mut s=source();s["parent_id"]=json!(P);s["is_sub_chat"]=json!(true);let a=merge_startup(&s,&Value::Null,C,O,None,false,3).unwrap();assert_eq!(a["parent_id"],P);assert_eq!(a["is_sub_chat"],true);assert_eq!(a["pinned"],true);assert_eq!(a["opaqueUserMetadata"],s["opaqueUserMetadata"]);assert_eq!(a["messages_v"],99);assert!(a.get("messages").is_none());assert_eq!(a["is_metadata_only"],true);}
 // contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,sync.phase2.drafts.authoritative-encrypted
 #[test]fn startup_partial_row_keeps_clear_floor_unknown_extensions_and_exact_absence(){let b=json!({"chat_id":C,"id":null,"draft_v":9,"cleared_draft_v":9,"encrypted_draft_md":null,"custom":{"nested":[1,null]},"processing_metadata":true});let mut s=source();s["draft_v"]=json!(8);s["encrypted_draft_md"]=json!("stale");let a=merge_startup(&s,&b,C,O,None,false,3).unwrap();for f in ["id","draft_v","cleared_draft_v","encrypted_draft_md","custom","processing_metadata"]{assert_eq!(a[f],b[f]);}assert!(a.get("encrypted_draft_preview").is_none());}
 // contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,sync.phase2.drafts.authoritative-encrypted
 #[test]fn startup_newer_encrypted_draft_and_explicit_clear_respect_local_floor(){let b=json!({"chat_id":C,"draft_v":8,"cleared_draft_v":7,"encrypted_draft_md":"local"});let mut s=source();s["draft_v"]=json!(9);s["encrypted_draft_md"]=json!("incoming");s["encrypted_draft_preview"]=json!("opaque");let a=merge_startup(&s,&b,C,O,None,false,3).unwrap();assert_eq!(a["draft_v"],9);assert_eq!(a["encrypted_draft_md"],"incoming");assert_eq!(a["cleared_draft_v"],7);s["draft_v"]=json!(0);s["encrypted_draft_md"]=Value::Null;s["cleared_draft_v"]=json!(10);let a=merge_startup(&s,&a,C,O,None,false,3).unwrap();assert_eq!(a["encrypted_draft_md"],Value::Null);assert_eq!(a["cleared_draft_v"],10);}
 // contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,sync.deletion.partial-window-not-authoritative
 #[test]fn startup_full_keyed_row_updates_only_metadata_without_promoting_message_content(){let b=json!({"chat_id":C,"encrypted_chat_key":"oldwrap","is_metadata_only":false,"messages_v":5,"messages":[{"opaque":"existing"}],"title_v":1,"metadata_v":1,"custom":[1]});let a=merge_startup(&source(),&b,C,O,None,false,3).unwrap();assert_eq!(a["encrypted_title"],"server");assert_eq!(a["messages"],b["messages"]);assert_eq!(a["messages_v"],5);assert_eq!(a["is_metadata_only"],false);assert_eq!(a["custom"],b["custom"]);let mut omitted=source();omitted["encrypted_chat_key"]=Value::Null;assert_eq!(merge_startup(&omitted,&b,C,O,None,false,3).unwrap()["encrypted_chat_key"],"oldwrap");}
 // contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
 #[test]fn expanded_metadata_preserves_existing_full_record_byte_shape(){let b=json!({"chat_id":C,"encrypted_chat_key":"localwrap","is_metadata_only":false,"title_v":9,"metadata_v":9,"draft_v":8,"encrypted_draft_md":"local","custom":{"nil":null}});assert_eq!(*merge_startup(&source(),&b,C,O,None,true,3).unwrap(),b);}
 // contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.authoritative-enforcement
 #[test]fn actual_team_selector_allows_opaque_team_child_but_never_cross_scope_or_self_parent(){let mut s=source();s["team_id"]=json!(T);s["user_id"]=json!(P);s["parent_id"]=json!(P);s["is_sub_chat"]=json!(true);let a=merge_startup(&s,&Value::Null,C,O,Some(T),false,3).unwrap();assert_eq!(a["team_id"],T);assert_eq!(a["parent_id"],P);assert!(merge_startup(&s,&Value::Null,C,O,None,false,3).is_err());s["parent_id"]=json!(C);assert!(merge_startup(&s,&Value::Null,C,O,Some(T),false,3).is_err());}
 // contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.authoritative-enforcement
 #[test]fn startup_foreign_record_bad_cipher_plaintext_and_independent_rollback_refuse(){for b in [json!({"chat_id":O}),json!({"chat_id":C,"user_id":P}),json!({"chat_id":C,"title_v":3,"metadata_v":1}),json!({"chat_id":C,"title_v":1,"metadata_v":3})]{assert!(merge_startup(&source(),&b,C,O,None,false,3).is_err());}for(field,value)in [("encrypted_title",json!(false)),("title",json!("plaintext")),("messages",json!([])),("draft_v",json!(false))]{let mut s=source();s[field]=value;assert!(merge_startup(&s,&Value::Null,C,O,None,false,3).is_err());}}
}

// Serialized navigation metadata/proof bytes, not a process-RAM quota. Known
// content/window/sidecar resources retain their independent existing bounds.
pub(super) fn reserve_startup_metadata_evidence(used:usize,before:&Value,after:&Value)->Result<usize>{
    let limit=crate::client::transport::MAX_BODY;
    let bytes=crate::client::monitor::cached_view::bounded_bytes(&(before,after),limit.saturating_sub(used)).ok_or(Error::Protocol)?;
    // Exact row values plus a conservative fixed envelope for the actual native
    // result's canonical UUIDs, safe DB version, tags and JSON framing.
    used.checked_add(bytes).and_then(|n|n.checked_add(512)).filter(|n|*n<=limit).ok_or(Error::Protocol)
}

#[cfg(test)]mod startup_review_v2_tests {
 use super::*;
 const C:&str="11111111-1111-4111-8111-111111111111";const O:&str="22222222-2222-4222-8222-222222222222";const T:&str="33333333-3333-4333-8333-333333333333";
 fn source()->Value{json!({"id":C,"encrypted_chat_key":"incoming-rewrap-or-conflict","anonymous_encrypted_chat_key":"incoming-anonymous","encrypted_title":"canonical","title_v":2,"metadata_v":2,"messages_v":99})}
 // contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.authoritative-enforcement
 #[test]fn opaque_startup_has_no_authority_to_replace_nonempty_existing_wrapped_keys_and_does_not_reject_rewrap_strings(){
  let before=json!({"chat_id":C,"encrypted_chat_key":"original","anonymous_encrypted_chat_key":"old-anonymous","messages_v":5,"title_v":1,"metadata_v":1});
  let after=merge_startup(&source(),&before,C,O,None,false,3).unwrap();assert_eq!(after["encrypted_chat_key"],"original");assert_eq!(after["anonymous_encrypted_chat_key"],"old-anonymous");assert_eq!(after["encrypted_title"],"canonical");assert_eq!(after["messages_v"],5);
 }
 // contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,sync.deletion.partial-window-not-authoritative
 #[test]fn missing_or_null_legacy_metadata_only_flag_keeps_expanded_full_row_exact_and_ordinary_content_count(){
  for flag in [None,Some(Value::Null)]{
   let mut before=json!({"chat_id":C,"encrypted_chat_key":"original","messages_v":5,"title_v":1,"metadata_v":1,"custom":{"nil":null}});if let Some(flag)=flag{before["is_metadata_only"]=flag;}
   assert_eq!(*merge_startup(&source(),&before,C,O,None,true,3).unwrap(),before);
   let after=merge_startup(&source(),&before,C,O,None,false,3).unwrap();assert_eq!(after["messages_v"],5);assert_eq!(after.get("is_metadata_only"),before.get("is_metadata_only"));
  }
 }
 // contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.authoritative-enforcement
 #[test]fn existing_physical_personal_or_unknown_scope_never_becomes_team_while_actual_same_team_partial_is_supported(){
  let mut source=source();source["team_id"]=json!(T);
  for scope in [None,Some(Value::Null),Some(json!("")),Some(json!(O))]{let mut before=json!({"chat_id":C});if let Some(scope)=scope{before["team_id"]=scope;}assert!(merge_startup(&source,&before,C,O,Some(T),false,3).is_err());}
  let before=json!({"chat_id":C,"team_id":T,"draft_v":9,"encrypted_draft_md":"local"});let after=merge_startup(&source,&before,C,O,Some(T),false,3).unwrap();assert_eq!(after["team_id"],T);assert_eq!(after["encrypted_draft_md"],"local");assert!(merge_startup(&source,&Value::Null,C,O,Some(T),false,3).is_ok());
 }
 // contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy
 #[test]fn source_plus_evidence_budget_refuses_before_the_current_write_without_excluding_unknown_fields(){
  let limit=crate::client::transport::MAX_BODY;let source=json!({"unknownOpaqueExtension":"x".repeat(limit/2)});let source_bytes=crate::client::monitor::cached_view::bounded_bytes(&source,limit).unwrap();
  let before=json!({"unknownPhysicalExtension":"y".repeat(limit/4)});let after=before.clone();
  assert!(reserve_startup_metadata_evidence(source_bytes,&before,&after).is_err());
  assert!(reserve_startup_metadata_evidence(0,&before,&after).is_ok());assert!(source_bytes<limit);
  // The actual driver reserves this result before native compare_store. Neither
  // source nor previous physical records are consumed to recover capacity.
  assert_eq!(source["unknownOpaqueExtension"].as_str().unwrap().len(),limit/2);assert_eq!(before,after);
 }
}

/// Main metadata is a partial facet. Preserve transcript/draft/finality fields
/// byte-for-byte even if an upstream metadata projection later grows.
pub(super) fn merge_main_recovered_metadata(source:&Value,before:&Value,chat:&str,owner:&str)->Result<Plain<Value>>{
 let after=merge_recovered_metadata(source,before,chat,owner)?;
 for field in ["messages_v","messages","history","updated_at","last_edited_overall_timestamp","draft_v","cleared_draft_v","encrypted_draft_md","encrypted_draft_preview","is_metadata_only","processing_metadata"]{
  if after.get(field)!=before.get(field){return Err(Error::Protocol)}
 }
 Ok(after)
}
#[cfg(test)]mod main_metadata_facet_tests {
 use super::*;
 const C:&str="11111111-1111-4111-8111-111111111111";const O:&str="22222222-2222-4222-8222-222222222222";
 fn before()->Value{json!({"chat_id":C,"team_id":null,"user_id":O,"encrypted_chat_key":"actual-original-wrap","metadata_v":3,"title_v":4,"messages_v":7,"updated_at":100,"last_edited_overall_timestamp":101,"draft_v":9,"cleared_draft_v":8,"encrypted_draft_md":"actual-draft","is_metadata_only":false,"processing_metadata":true,"custom":{"nested":[null,"雪"]}})}
 fn source()->Value{json!({"id":C,"team_id":null,"user_id":O,"encrypted_chat_key":"legitimate-rewrap","metadata_v":4,"title_v":5,"messages_v":99,"updated_at":999,"last_edited_overall_timestamp":1000,"encrypted_title":"actual-canonical-title","encrypted_chat_summary":"actual-canonical-summary"})}
 // contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,chats.persistence.client-encrypted
 #[test]fn main_metadata_never_claims_unstored_transcript_or_overwrites_local_draft_and_extensions(){let b=before();let a=merge_main_recovered_metadata(&source(),&b,C,O).unwrap();for field in ["messages_v","updated_at","last_edited_overall_timestamp","draft_v","cleared_draft_v","encrypted_draft_md","is_metadata_only","processing_metadata","custom","encrypted_chat_key"]{assert_eq!(a.get(field),b.get(field));}assert_eq!(a["metadata_v"],4);assert_eq!(a["title_v"],5);assert_eq!(a["encrypted_title"],"actual-canonical-title");}
 // contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,auth.session.isolation
 #[test]fn main_metadata_refuses_both_independent_rollbacks_foreign_scope_and_plaintext(){let b=before();for(field,value)in [("metadata_v",json!(2)),("title_v",json!(3)),("user_id",json!(C)),("team_id",json!(O)),("messages",json!([])),("title",json!("plaintext"))]{let mut s=source();s[field]=value;assert!(merge_main_recovered_metadata(&s,&b,C,O).is_err());assert_eq!(b["messages_v"],7);}}
 // contract-test: supporting surface=sdks.rust assertions=sync.client.shared-rust-policy,sync.phase2.drafts.authoritative-encrypted
 #[test]fn main_metadata_preserves_actual_missing_null_and_clear_floors(){for shape in [json!({}),json!({"encrypted_draft_md":null,"encrypted_draft_preview":null,"cleared_draft_v":99}),json!({"messages":[],"history":null,"updated_at":null})]{let mut b=before();b.as_object_mut().unwrap().extend(shape.as_object().unwrap().clone());let a=merge_main_recovered_metadata(&source(),&b,C,O).unwrap();for field in ["encrypted_draft_md","encrypted_draft_preview","cleared_draft_v","messages","history","updated_at"]{assert_eq!(a.get(field),b.get(field));}}}
}
