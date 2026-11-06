//! Display order DATA only. Never freshness, inventory, deletion or recovery authority.
use super::*;
pub(super) const SNAPSHOT_FIELD:&str="chat_arrival_order_v1";
pub(super) fn restore(value:Option<&Value>,chats:&BTreeMap<String,Value>)->Result<Option<Vec<String>>>{
    let Some(value)=value else{return Ok(None)};
    let object=value.as_object().ok_or(Error::Protocol)?;
    if object.len()!=2||value["version"].as_u64()!=Some(1){return Err(Error::Protocol)}
    let ids=value["ids"].as_array().ok_or(Error::Protocol)?;
    // Allocation and total identifier bytes bounded by already accepted metadata,
    // never a new independent capacity allowance. No snapshot quota is raised.
    if ids.len()!=chats.len(){return Err(Error::Protocol)}
    let mut seen=std::collections::BTreeSet::new();let mut result=Vec::with_capacity(ids.len());
    for id in ids {let id=id.as_str().ok_or(Error::Protocol)?;
        if !chats.contains_key(id)||!seen.insert(id){return Err(Error::Protocol)}
        result.push(id.to_owned());
    }
    Ok(Some(result))
}
impl Client {
    pub(super) fn insert_chat_row(&mut self,id:String,row:Value)->Option<Value>{
        // Every replacement path keeps the server counter until a row states a new one.
        let mut row=row;
        self.carry_cached_unread_count(&id,&mut row);
        if !self.chats.contains_key(&id) {if let Some(order)=&mut self.chat_arrival_order {order.push(id.clone());}}
        self.chats.insert(id,row)
    }
    pub(super) fn remove_chat_row(&mut self,id:&str)->Option<Value>{
        if let Some(order)=&mut self.chat_arrival_order {order.retain(|entry|entry!=id);}
        self.chat_details_cache.remove(id);
        self.chats.remove(id)
    }
    pub(super) fn clear_chat_rows(&mut self){self.chats.clear();self.chat_arrival_order=None;}
    // A preexisting map-only batch cannot manufacture original response order.
    pub(super) fn extend_chat_rows_without_arrival(&mut self,updates:BTreeMap<String,Value>){
        if updates.keys().any(|id|!self.chats.contains_key(id)){self.chat_arrival_order=None;}
        self.chats.extend(updates);
    }
    pub(super) fn current_chat_arrival_order(&self)->Option<&Vec<String>>{
        let ids=self.chat_arrival_order.as_ref()?;
        if ids.len()!=self.chats.len(){return None}
        let mut seen=std::collections::BTreeSet::new();
        if ids.iter().any(|id|!self.chats.contains_key(id)||!seen.insert(id)){return None}
        Some(ids)
    }
    pub(super) fn chat_rows_in_arrival_order(&self)->Vec<&Value>{
        match self.current_chat_arrival_order() {
            Some(ids)=>ids.iter().filter_map(|id|self.chats.get(id)).collect(),
            None=>self.chats.values().collect(),
        }
    }
}
#[cfg(test)]
#[path="chat_arrival_order_tests.rs"]
mod tests;
