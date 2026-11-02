//! Focus authority comes from encrypted current metadata, never chat prose.
use super::{
    sync::decrypt_optional,
    transport::{Socket, send, wait},
    *,
};
impl Client {
    pub(super) fn current_focus_state(
        &self,
        chat: &str,
        key: &[u8; 32],
    ) -> Result<(Option<String>, Value)> {
        let Some(row) = self.chats.get(chat) else {
            return Ok((None, json!({})));
        };
        let focus = decrypt_optional(row, "encrypted_active_focus_id", key)?;
        if focus.len() > 255 || focus.chars().any(char::is_control) {
            return Err(Error::Protocol);
        }
        let phase = decrypt_optional(row, "encrypted_focus_phase_state", key)?;
        let phase = if phase.is_empty() {
            json!({})
        } else {
            serde_json::from_str(&phase)?
        };
        validate_states(chat, &phase)?;
        Ok(((!focus.is_empty()).then_some(focus), phase))
    }
    pub(super) async fn persist_focus_event(
        &mut self,
        ws: &mut Socket,
        kind: &str,
        event: &Value,
        chat: &str,
        key: &[u8; 32],
        previous: &mut Value,
    ) -> Result<()> {
        let mut plan=FocusPersistencePlan::prepare(kind,event,chat,key,previous)?;
        while let Some(effect)=plan.next_effect(key,||self.team().map(|team|team.map(str::to_owned)))? {
            let(kind,payload,ack)=effect.into_wire();
            send(ws,kind,payload).await?;
            if let Some(ack)=ack{let(kind,field,value)=ack.wire_parts();wait(ws,kind,field,value).await?;}
        }
        plan.into_update()?.apply_to_chats(chat,&mut self.chats,previous)
    }
}
/// Pure, private ciphertext effects from the existing selected focus event.
/// This plan is not an ACK, storage receipt, scope or publication authority.
/// Callers must await each actual send/ACK before asking for the next effect.
pub(super) struct FocusPersistencePlan {
    chat:String,
    expected_previous:super::plaintext::Plain<Value>,
    mode:FocusPlanMode,
    exhausted:bool,
}
enum FocusPlanMode {
    Activation {encrypted:String,pending:bool},
    States {
        states:super::plaintext::Plain<Value>,encrypted:String,metadata_pending:bool,
        keys:super::plaintext::Plain<Vec<String>>,focus:usize,transition:usize,
        seen:super::plaintext::Plain<BTreeMap<String,Value>>,
    },
}
pub(super) struct FocusPersistenceEffect {kind:&'static str,payload:Value,ack:Option<FocusPersistenceAck>}
pub(super) struct FocusPersistenceAck {kind:&'static str,field:&'static str,value:String}
impl FocusPersistenceEffect {
    pub(super) fn into_wire(self)->(&'static str,Value,Option<FocusPersistenceAck>){(self.kind,self.payload,self.ack)}
}
impl FocusPersistenceAck {
    pub(super) fn wire_parts(&self)->(&'static str,&'static str,&str){(self.kind,self.field,&self.value)}
}
/// Exact local patch only, never durability/recovery/read authority. Its final
/// caller must also check original scope and row stamp under the Client borrow.
pub(super) struct FocusPersistenceUpdate {
    chat:String,expected_previous:super::plaintext::Plain<Value>,encrypted:String,
    states:Option<super::plaintext::Plain<Value>>,
}
impl FocusPersistencePlan {
    pub(super) fn prepare(kind:&str,event:&Value,chat:&str,key:&[u8;32],previous:&mut Value)->Result<Self>{
        use super::plaintext::Plain;
        if text(event,"chat_id")!=chat{return Err(Error::Forbidden)}
        let mode=if kind=="focus_mode_activated" {
            let focus=required(event,"focus_id")?;
            if focus.len()>255||focus.chars().any(char::is_control){return Err(Error::Protocol)}
            // SAME prior scratch mutation, before activation encryption. No Team
            // lookup or phase-state interpretation belongs to this branch.
            if !focus.starts_with("project-"){previous.as_object_mut().ok_or(Error::Protocol)?.remove(focus);}
            FocusPlanMode::Activation{encrypted:crypto::encrypt_combined(focus,key)?,pending:true}
        } else {
            let mut states=Plain::new(event["states"].clone());
            validate_states(chat,&states)?;
            for(id,state)in states.as_object_mut().ok_or(Error::Protocol)? {
                if let Some(old)=previous.get(id)
                    &&old["run_id"]==state["run_id"]
                    &&old["version"].as_u64()>state["version"].as_u64(){
                    *state=old.clone();
                }
            }
            // Preserve initial state encryption before the first lazy Team
            // lookup; individual transition encryption stays AFTER metadata ACK.
            let encrypted=crypto::encrypt_combined(&states.to_string(),key)?;
            let keys=Plain::new(states.as_object().ok_or(Error::Protocol)?.keys().cloned().collect());
            FocusPlanMode::States{states,encrypted,metadata_pending:true,keys,focus:0,transition:0,seen:Plain::new(BTreeMap::new())}
        };
        Ok(Self{chat:chat.into(),expected_previous:Plain::new(previous.clone()),mode,exhausted:false})
    }
    pub(super) fn next_effect(&mut self,key:&[u8;32],mut team:impl FnMut()->Result<Option<String>>)->Result<Option<FocusPersistenceEffect>>{
        match &mut self.mode {
            FocusPlanMode::Activation{encrypted,pending}=>{
                if *pending {*pending=false;return Ok(Some(FocusPersistenceEffect{kind:"update_encrypted_active_focus_id",payload:json!({"chat_id":self.chat,"encrypted_active_focus_id":encrypted}),ack:None}))}
            },
            FocusPlanMode::States{states,encrypted,metadata_pending,keys,focus,transition,seen}=>{
                if *metadata_pending {
                    let mut payload=json!({"chat_id":self.chat,"encrypted_focus_phase_state":encrypted});
                    if let Some(team)=team()?{payload["team_id"]=json!(team);}
                    *metadata_pending=false;
                    return Ok(Some(FocusPersistenceEffect{kind:"encrypted_chat_metadata",payload,ack:Some(FocusPersistenceAck{kind:"encrypted_metadata_stored",field:"chat_id",value:self.chat.clone()})}));
                }
                while *focus<keys.len() {
                    // A previously newer same-run state is deliberately not
                    // revalidated or eagerly encrypted: original failure order
                    // remains metadata send/ACK, then this transition traversal.
                    let transitions=states.get(keys[*focus].as_str()).ok_or(Error::Protocol)?["transitions"].as_array().ok_or(Error::Protocol)?;
                    if *transition>=transitions.len(){*focus+=1;*transition=0;continue}
                    let value=&transitions[*transition];*transition+=1;
                    let id=required(value,"event_id")?;
                    if seen.contains_key(id){continue}
                    seen.insert(id.to_owned(),Value::Null);
                    let mut payload=json!({"chat_id":self.chat,"message":{"message_id":id,"role":"system","status":"synced","encrypted_content":crypto::encrypt_combined(&value.to_string(),key)?,"created_at":value["created_at"]}});
                    if let Some(team)=team()?{payload["team_id"]=json!(team);}
                    return Ok(Some(FocusPersistenceEffect{kind:"chat_system_message_added",payload,ack:Some(FocusPersistenceAck{kind:"system_message_confirmed",field:"message_id",value:id.into()})}));
                }
            },
        }
        self.exhausted=true;Ok(None)
    }
    pub(super) fn into_update(self)->Result<FocusPersistenceUpdate>{
        if !self.exhausted{return Err(Error::Protocol)}
        let(encrypted,states)=match self.mode {
            FocusPlanMode::Activation{encrypted,..}=>(encrypted,None),
            FocusPlanMode::States{encrypted,states,..}=>(encrypted,Some(states)),
        };
        Ok(FocusPersistenceUpdate{chat:self.chat,expected_previous:self.expected_previous,encrypted,states})
    }
}
impl FocusPersistenceUpdate {
    pub(super) fn apply_to_chats(self,chat:&str,chats:&mut BTreeMap<String,Value>,previous:&mut Value)->Result<()> {
        use super::plaintext::Wipe;
        if self.chat!=chat{return Err(Error::Cancelled)}
        if *previous!=*self.expected_previous{return Err(Error::Conflict)}
        let field=if self.states.is_some(){"encrypted_focus_phase_state"}else{"encrypted_active_focus_id"};
        if let Some(row)=chats.get_mut(chat){row[field]=json!(self.encrypted);}
        if let Some(states)=self.states{previous.wipe();*previous=states.into_inner();}
        Ok(())
    }
}

fn validate_states(chat: &str, states: &Value) -> Result<()> {
    let map = states.as_object().ok_or(Error::Protocol)?;
    if map.len() > 100 || states.to_string().len() > 1_000_000 {
        return Err(Error::Protocol);
    }
    for (focus, state) in map {
        if focus.is_empty()
            || focus.len() > 255
            || state["schema_version"] != 1
            || text(state, "chat_id") != chat
            || text(state, "focus_id") != focus
            || state["version"].as_u64().is_none()
            || text(state, "run_id").is_empty()
        {
            return Err(Error::Protocol);
        }
        let transitions = state["transitions"].as_array().ok_or(Error::Protocol)?;
        if transitions.len() > 32 {
            return Err(Error::Protocol);
        }
        for t in transitions {
            if text(t, "chat_id") != chat
                || text(t, "focus_id") != focus
                || text(t, "event_id").is_empty()
                || text(t, "event_id").len() > 255
                || t["created_at"].as_u64().is_none()
            {
                return Err(Error::Protocol);
            }
        }
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn phases_cannot_restore_foreign_chat_or_focus() {
        let valid = json!({"focus":{"schema_version":1,"chat_id":"chat","focus_id":"focus","run_id":"run","version":0,"transitions":[]}});
        assert!(validate_states("chat", &valid).is_ok());
        assert!(validate_states("other", &valid).is_err());
        let mut wrong = valid;
        wrong["focus"]["transitions"] =
            json!([{"event_id":"event","chat_id":"other","focus_id":"focus","created_at":1}]);
        assert!(validate_states("chat", &wrong).is_err());
    }
    fn focus_state(version:u64,transitions:Value)->Value {
        json!({"schema_version":1,"chat_id":"chat","focus_id":"focus","run_id":"same-run","version":version,"transitions":transitions})
    }
    // contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.surface.semantic-parity
    #[test]
    fn activation_resets_scratch_and_never_consumes_team_error(){
        let key=[7;32];let mut previous=json!({"focus":{"old":"scratch"},"other":{"keep":true}});
        let mut plan=FocusPersistencePlan::prepare("focus_mode_activated",&json!({"chat_id":"chat","focus_id":"focus"}),"chat",&key,&mut previous).unwrap();
        assert!(previous.get("focus").is_none());assert_eq!(previous["other"]["keep"],true);
        let(kind,payload,ack)=plan.next_effect(&key,||Err(Error::Expired)).unwrap().unwrap().into_wire();
        assert_eq!(kind,"update_encrypted_active_focus_id");assert!(ack.is_none());
        assert_eq!(crypto::decrypt_combined(payload["encrypted_active_focus_id"].as_str().unwrap(),&key).unwrap(),"focus");
        assert!(plan.next_effect(&key,||Err(Error::Expired)).unwrap().is_none());
        let mut chats=BTreeMap::from([("chat".into(),json!({"keep":true}))]);
        plan.into_update().unwrap().apply_to_chats("chat",&mut chats,&mut previous).unwrap();
        assert_eq!(chats["chat"]["keep"],true);assert_eq!(chats["chat"]["encrypted_active_focus_id"],payload["encrypted_active_focus_id"]);
    }
    // contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.surface.semantic-parity
    #[test]
    fn non_activation_kind_keeps_metadata_first_then_lazy_original_transition_order_and_dedup(){
        let key=[8;32];let one=json!({"event_id":"event-one","chat_id":"chat","focus_id":"focus","created_at":1});let two=json!({"event_id":"event-two","chat_id":"chat","focus_id":"focus","created_at":2});
        let states=json!({"focus":focus_state(1,json!([one,one,two]))});let mut previous=json!({});
        let mut plan=FocusPersistencePlan::prepare("legacy-other-focus-kind",&json!({"chat_id":"chat","states":states}),"chat",&key,&mut previous).unwrap();let mut lookups=0;
        let(kind,payload,ack)=plan.next_effect(&key,||{lookups+=1;Ok(Some("team".into()))}).unwrap().unwrap().into_wire();
        assert_eq!(kind,"encrypted_chat_metadata");assert_eq!(payload["team_id"],"team");assert_eq!(serde_json::from_str::<Value>(&crypto::decrypt_combined(payload["encrypted_focus_phase_state"].as_str().unwrap(),&key).unwrap()).unwrap(),states);
        assert_eq!(ack.unwrap().wire_parts(),("encrypted_metadata_stored","chat_id","chat"));
        let mut ids=vec![];
        while let Some(effect)=plan.next_effect(&key,||{lookups+=1;Ok(Some("team".into()))}).unwrap(){let(kind,payload,ack)=effect.into_wire();assert_eq!(kind,"chat_system_message_added");assert_eq!(payload["team_id"],"team");let id=payload["message"]["message_id"].as_str().unwrap();assert_eq!(ack.as_ref().unwrap().wire_parts(),("system_message_confirmed","message_id",id));ids.push(id.to_owned());}
        assert_eq!(ids,vec!["event-one","event-two"]);assert_eq!(lookups,3);
        let mut chats=BTreeMap::new();plan.into_update().unwrap().apply_to_chats("chat",&mut chats,&mut previous).unwrap();assert_eq!(previous,states);assert!(chats.is_empty(),"original absent row is never fabricated");
    }
    // contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.surface.semantic-parity
    #[test]
    fn newer_prior_state_transition_shape_failure_stays_after_initial_metadata_effect(){
        let key=[9;32];let fresh=json!({"focus":focus_state(0,json!([]))});let mut previous=json!({"focus":focus_state(2,json!("original malformed retained transition shape"))});
        let mut plan=FocusPersistencePlan::prepare("phase",&json!({"chat_id":"chat","states":fresh}),"chat",&key,&mut previous).unwrap();
        let(kind,_,ack)=plan.next_effect(&key,||Ok(None)).unwrap().unwrap().into_wire();assert_eq!(kind,"encrypted_chat_metadata");assert!(ack.is_some());
        assert!(matches!(plan.next_effect(&key,||Ok(None)),Err(Error::Protocol)),"do not eagerly reject a merged prior state before original metadata send/ACK");
    }
    // contract-test: supporting surface=sdks.rust assertions=auth.session.isolation,sdk.surface.semantic-parity
    #[test]
    fn final_focus_patch_rejects_changed_previous_or_chat_without_mutating_rows(){
        let key=[10;32];
        for changed_chat in [false,true] {
            let mut previous=json!({});let mut plan=FocusPersistencePlan::prepare("phase",&json!({"chat_id":"chat","states":{"focus":focus_state(0,json!([]))}}),"chat",&key,&mut previous).unwrap();
            while plan.next_effect(&key,||Ok(None)).unwrap().is_some(){}
            let update=plan.into_update().unwrap();let mut chats=BTreeMap::from([("chat".into(),json!({"encrypted_focus_phase_state":"original","keep":true}))]);let before=chats.clone();
            if !changed_chat{previous["intervening"]=json!(true);}
            assert_eq!(update.apply_to_chats(if changed_chat{"different"}else{"chat"},&mut chats,&mut previous).err(),Some(if changed_chat{Error::Cancelled}else{Error::Conflict}));assert_eq!(chats,before);
        }
    }
}
