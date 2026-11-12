use super::sync::decrypt_optional;
use super::*;
impl Client {
    pub(super) async fn embed_detail(&mut self, id: &str) -> Result<Item> {
        uuid::Uuid::parse_str(id).map_err(|_| Error::Invalid("A full embed ID is required."))?;
        let wrapping = self.wrapping_key().await?;
        let mut wanted = id.to_owned();
        let mut visited = std::collections::HashSet::new();
        let mut ws = self.socket().await?;
        while visited.insert(wanted.clone()) && visited.len() <= 8 {
            let mut payload = json!({"embed_id":wanted});
            if let Some(team) = self.team()? {
                payload["team_id"] = json!(team);
                let chat_hash = self
                    .embeds
                    .get(&wanted)
                    .map(|v| text(v, "hashed_chat_id"))
                    .filter(|v| !v.is_empty());
                let chat =
                    chat_hash.and_then(|hash| self.chats.keys().find(|id| sha256(id) == hash));
                payload["chat_id"] = json!(chat.ok_or(Error::Invalid(
                    "Open the original Team chat before opening its saved result."
                ))?);
            }
            transport::send(&mut ws, "request_embed", payload).await?;
            let response = transport::wait(&mut ws, "send_embed_data", "embed_id", &wanted).await?;
            let row = response.get("payload").unwrap_or(&response);
            if row["already_encrypted"] != true || text(row, "embed_id") != wanted {
                return Err(Error::Forbidden);
            }
            let chat = text(row, "chat_id");
            let chat_hash = if chat.len() == 64 && chat.bytes().all(|c| c.is_ascii_hexdigit()) {
                chat.to_owned()
            } else {
                sha256(chat)
            };
            let encrypted = json!({"embed_id":wanted,"encrypted_type":row["type"],"encrypted_content":row["content"],"encrypted_text_preview":row["encrypted_text_preview"],"hashed_chat_id":chat_hash,"parent_embed_id":row["parent_embed_id"],"status":row["status"],"version_number":row["version_number"],"updated_at":row["updatedAt"]});
            self.embeds.insert(wanted.clone(), encrypted);
            for wrapper in row["embed_keys"].as_array().ok_or(Error::Protocol)? {
                if text(wrapper, "hashed_embed_id") != sha256(&wanted) {
                    return Err(Error::Forbidden);
                }
                self.embed_keys.push(wrapper.clone());
            }
            let parent = text(row, "parent_embed_id");
            if parent.is_empty()
                || self
                    .embed_key(&wanted, &wrapping, &mut std::collections::HashSet::new())
                    .is_ok()
            {
                break;
            }
            wanted = parent.into();
        }
        let _ = ws.close(None).await;
        self.decrypt_embed_item(id, &wrapping)
    }
    pub(super) fn decrypt_embed_item(&self, id: &str, wrapping: &[u8; 32]) -> Result<Item> {
        let key = self.embed_key(id, wrapping, &mut std::collections::HashSet::new())?;
        let row = self.embeds.get(id).ok_or(Error::Protocol)?;
        let kind = decrypt_optional(row, "encrypted_type", &key)?;
        let preview = decrypt_optional(row, "encrypted_text_preview", &key)?;
        let content = super::toon::decode(&crypto::decrypt_combined(
            required(row, "encrypted_content")?,
            &key,
        )?)?;
        let title = ["title", "name", "filename"]
            .into_iter()
            .map(|k| text(&content, k))
            .find(|s| !s.is_empty())
            .unwrap_or(&kind);
        Ok(Item {
            id: id.into(),
            title: title.into(),
            description: preview,
            category: kind.clone(),
            status: text(row, "status").into(),
            fields: json!({"type":kind,"content":content}),
        })
    }
    /// Embed key from the cached wrappers (master, owning chat, then parent).
    pub(super) fn embed_key(
        &self,
        id: &str,
        wrapping: &[u8; 32],
        seen: &mut std::collections::HashSet<String>,
    ) -> Result<Key> {
        if !seen.insert(id.into()) || seen.len() > 8 {
            return Err(Error::Crypto);
        }
        let row = self.embeds.get(id).ok_or(Error::Protocol)?;
        let hash = sha256(id);
        for wrapper in self
            .embed_keys
            .iter()
            .filter(|w| text(w, "hashed_embed_id") == hash)
        {
            match text(wrapper, "key_type") {
                "master" if self.team()?.is_none() => {
                    return key_from_bytes(&crypto::decrypt_bytes(
                        required(wrapper, "encrypted_embed_key")?,
                        &self.require_session()?.master_key,
                    )?);
                }
                "chat" => {
                    let chat_hash = required(wrapper, "hashed_chat_id")?;
                    if let Some(chat) = self
                        .chats
                        .iter()
                        .find(|(id, _)| sha256(id) == chat_hash)
                        .map(|(_, r)| r)
                    {
                        let chat_key = self.chat_key(chat, wrapping)?;
                        return key_from_bytes(&crypto::decrypt_bytes(
                            required(wrapper, "encrypted_embed_key")?,
                            &chat_key,
                        )?);
                    }
                }
                _ => {}
            }
        }
        let parent = text(row, "parent_embed_id");
        if !parent.is_empty() {
            return self.embed_key(parent, wrapping, seen);
        }
        Err(Error::Forbidden)
    }
    pub(super) async fn wiki_detail(&mut self, title: &str) -> Result<Item> {
        if title.is_empty() || title.len() > 512 {
            return Err(Error::Invalid("Invalid Wikipedia title."));
        }
        let response = self
            .request(
                Method::GET,
                &format!("/v1/wikipedia/summary?title={}&language=en", segment(title)),
                None,
            )
            .await?;
        Ok(Item {
            id: format!("wiki:{title}"),
            title: response
                .get("title")
                .and_then(Value::as_str)
                .unwrap_or(title)
                .into(),
            description: response
                .get("extract")
                .or_else(|| response.get("description"))
                .and_then(Value::as_str)
                .unwrap_or("")
                .into(),
            category: "wikipedia".into(),
            fields: response,
            ..Item::default()
        })
    }
}

#[path="saved_embed_key_phases.rs"]
pub(in crate::client) mod selected_key;
// Version reads reuse the same first master -> cached owning chat -> parent
// key policy, through genuine opaque master AES. Cold chat-only wrappers and
// Team/Project selectors remain explicit unsupported slices, not key fallbacks.
impl Client {
    pub(super) async fn cached_version_embed_key(
        &self,id:&str,scope:&super::embed_version::VersionReadScope,
        staged:&BTreeMap<String,Value>,keys:&[Value],
    )->Result<Key>{
        self.selected_embed_key(id,scope,staged,keys,true).await
    }
    /// Fresh saved reads may use only their admitted rows/wrappers. The shared
    /// wrapper/key engine remains identical; version reads retain cache policy.
    pub(super) async fn selected_embed_key(
        &self,id:&str,scope:&super::embed_version::VersionReadScope,
        staged:&BTreeMap<String,Value>,keys:&[Value],allow_cached:bool,
    )->Result<Key>{
        selected_key::select(&selected_key::Borrowed{client:self,scope},id,staged,keys,allow_cached).await
    }
    pub(super) async fn version_embed_key(&mut self,id:&str,scope:&super::embed_version::VersionReadScope)->Result<Key>{
        let mut staged=BTreeMap::new();let mut keys=vec![];
        match self.cached_version_embed_key(id,scope,&staged,&keys).await {
            Ok(key)=>{scope.check(self)?;return Ok(key)},Err(Error::Forbidden|Error::Crypto|Error::Unavailable{code:"cookie_embed_version_key_cache_unavailable",..})=>{},Err(error)=>return Err(error),
        }
        scope.check(self)?;
        let mut ws=scope.run_io(self.socket_with_task_jobs(false)).await?;scope.check(self)?;
        let result=async {
            let mut wanted=id.to_owned();let mut visited=std::collections::HashSet::new();
            while visited.insert(wanted.clone())&&visited.len()<=8 {
                scope.check(self)?;
                scope.run_io(transport::send(&mut ws,"request_embed",json!({"embed_id":wanted}))).await?;scope.check(self)?;
                let response=scope.run_io(async{transport::wait(&mut ws,"send_embed_data","embed_id",&wanted).await.map(super::plaintext::Plain::new)}).await?;scope.check(self)?;
                let row=response.get("payload").unwrap_or(&response);
                if row["already_encrypted"]!=true||text(row,"embed_id")!=wanted{return Err(Error::Forbidden);}
                let chat=text(row,"chat_id");let chat_hash=if chat.len()==64&&chat.bytes().all(|v|v.is_ascii_hexdigit()){chat.to_owned()}else{sha256(chat)};
                staged.insert(wanted.clone(),json!({"embed_id":wanted,"encrypted_type":row["type"],"encrypted_content":row["content"],"encrypted_text_preview":row["encrypted_text_preview"],"hashed_chat_id":chat_hash,"parent_embed_id":row["parent_embed_id"],"status":row["status"]}));
                let wrappers=row["embed_keys"].as_array().filter(|rows|rows.len()<=1024).ok_or(Error::Protocol)?;
                for wrapper in wrappers {
                    if text(wrapper,"hashed_embed_id")!=sha256(&wanted){return Err(Error::Forbidden);}keys.push(wrapper.clone());
                }
                match self.cached_version_embed_key(id,scope,&staged,&keys).await {
                    Ok(key)=>{
                        scope.check(self)?;
                        for(id,row)in &staged {scope.check(self)?;self.embeds.insert(id.clone(),row.clone());}
                        scope.check(self)?;self.embed_keys.extend(keys.iter().cloned());return Ok(key)
                    },
                    Err(Error::Forbidden|Error::Crypto)=>{},Err(error)=>return Err(error),
                }
                let parent=text(row,"parent_embed_id");if parent.is_empty(){return Err(Error::Forbidden);}wanted=parent.into();
            }
            Err(Error::Crypto)
        }.await;
        let _=crate::platform::time::timeout(Duration::from_millis(100),ws.close(None)).await;
        scope.check(self)?;result
    }
}
