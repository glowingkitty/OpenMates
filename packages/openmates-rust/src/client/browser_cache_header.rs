//! Maintained metadata-only header builder; construction alone grants no authority.
use super::*;
fn truthy(v:&Value)->bool { match v {Value::Null=>false,Value::Bool(v)=>*v,Value::Number(v)=>v.as_f64().is_some_and(|v|v!=0.0),Value::String(v)=>!v.is_empty(),_=>true} }
fn or<'a>(values:impl IntoIterator<Item=Option<&'a Value>>,fallback:Value)->Value {
 values.into_iter().flatten().find(|v|truthy(v)).cloned().unwrap_or(fallback)
}
fn nullish<'a>(values:impl IntoIterator<Item=Option<&'a Value>>,fallback:Value)->Value {
 values.into_iter().flatten().find(|v|!v.is_null()).cloned().unwrap_or(fallback)
}
pub(super) fn build(details:&Value,existing:Option<&Value>,now:u64)->Result<Plain<Value>> {
 if !details.is_object()||now>MAX_SAFE {return Err(Error::Protocol)}
 let id=required(details,"id")?;uuid::Uuid::parse_str(id).map_err(|_|Error::Protocol)?;
 let mut out=Plain::new(json!({"chat_id":id,"title":null,"draft_v":0,"encrypted_draft_md":null,"encrypted_draft_preview":null,"processing_metadata":false,"waiting_for_metadata":false,"is_metadata_only":true}));
 for field in ["encrypted_title","encrypted_category","encrypted_icon","encrypted_chat_summary","encrypted_share_cta_text","encrypted_chat_tags","encrypted_follow_up_request_suggestions","encrypted_suggested_followup_message","encrypted_active_focus_id","encrypted_focus_phase_state","encrypted_auto_speak_response"] {out[field]=or([details.get(field)],Value::Null);}
 for field in ["messages_v","title_v","unread_count"] {out[field]=or([details.get(field)],json!(0));}
 // JavaScript undefined properties disappear on the existing JSON/IDB boundary;
 // explicit null values remain distinct.
 for field in ["metadata_v","ideabucket","ideabucket_processing_window_id","ideabucket_triggered_at"] {if let Some(v)=details.get(field){out[field]=v.clone();}}
 out["last_edited_overall_timestamp"]=or([details.get("last_edited_overall_timestamp"),details.get("updated_at")],json!(now));
 for field in ["created_at","updated_at"] {out[field]=or([details.get(field)],json!(now));}
 for field in ["encrypted_chat_key","anonymous_encrypted_chat_key"] {out[field]=or([details.get(field),existing.and_then(|e|e.get(field))],Value::Null);}
 for field in ["chat_visibility","participant_user_hashes"] {out[field]=nullish([details.get(field),existing.and_then(|e|e.get(field))],Value::Null);}
 out["pinned"]=or([details.get("pinned")],json!(false));
 for field in ["is_shared","is_private","share_pii"] {out[field]=nullish([details.get(field)],json!(false));}
 out["is_anonymous"]=nullish([details.get("is_anonymous"),existing.and_then(|e|e.get("is_anonymous"))],json!(false));
 out["share_highlights"]=nullish([details.get("share_highlights")],json!(true));
 Ok(out)
}
pub(super) fn validate_create(value:&Value,chat:&str,owner:&str)->Result<()> {
 projection(value,chat,owner,true)?;
 for field in ["messages_v","title_v","last_edited_overall_timestamp","unread_count","created_at","updated_at"] {safe_number(&value[field])?;}
 for field in ["metadata_v","ideabucket_triggered_at"] {if let Some(v)=value.get(field).filter(|v|!v.is_null()){safe_number(v)?;}}
 for field in ["pinned","is_shared","is_private","is_anonymous","share_pii","share_highlights"] {if !value[field].is_boolean(){return Err(Error::Protocol)}}
 if value["is_shared"]!=false||value["is_anonymous"]!=false{return Err(unsupported("ANONYMOUS_SHARED_HEADER_POLICY_REMAINS_REQUIRED"))}
 if value.get("ideabucket").is_some_and(|v|!v.is_null()&&!v.is_boolean())||value.get("ideabucket_processing_window_id").is_some_and(|v|!v.is_null()&&!v.is_string()){return Err(Error::Protocol)}
 let hashes=&value["participant_user_hashes"];
 if !hashes.is_null()&&!hashes.as_array().is_some_and(|a|a.iter().all(Value::is_string)){return Err(Error::Protocol)}
 if !value["anonymous_encrypted_chat_key"].is_null()&&!value["anonymous_encrypted_chat_key"].is_string(){return Err(Error::Protocol)}
 if value["is_metadata_only"]!=true||value["title"]!=Value::Null||value["draft_v"]!=0||!value["encrypted_draft_md"].is_null()||!value["encrypted_draft_preview"].is_null()||value["processing_metadata"]!=false||value["waiting_for_metadata"]!=false{return Err(Error::Protocol)}
 Ok(())
}
#[cfg(test)]mod tests {
 use super::*;
 #[test]fn shared_builder_vectors_match_exact_shape(){
 let fixture:Value=serde_json::from_str(include_str!("../../tests/fixtures/browser-metadata-only-header.json")).unwrap();
 for case in fixture["cases"].as_array().unwrap(){let existing=case.get("existing").filter(|v|!v.is_null());let actual=build(&case["details"],existing,case["now"].as_u64().unwrap()).unwrap();assert_eq!(*actual,case["expected"],"{}",case["id"]);}
 }
}
