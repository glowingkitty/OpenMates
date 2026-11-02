//! Private Task codecs. Plaintext private fields never become durable wire fields.
use super::tasks::*;
use super::*;
pub(super) struct Resolved {
    pub raw: Value,
    pub public: Value,
    pub key: Key,
}
pub(super) fn label_hashes(key: &[u8; 32], labels: &[String]) -> Result<Vec<String>> {
    let key = crypto::hkdf_sha256(key, &[], b"openmates-task-label-index-v1")?;
    normalized_labels(labels)
        .iter()
        .map(|label| hmac(&key, label.as_bytes()))
        .collect()
}
pub(super) fn normalized_labels(labels: &[String]) -> Vec<String> {
    let mut seen = std::collections::BTreeSet::new();
    labels
        .iter()
        .map(|s| {
            s.split_whitespace()
                .collect::<Vec<_>>()
                .join(" ")
                .to_lowercase()
        })
        .filter(|s| !s.is_empty() && seen.insert(s.clone()))
        .collect()
}
pub(super) fn hmac(key: &[u8; 32], value: &[u8]) -> Result<String> {
    use hmac::{Hmac, Mac};
    let mut mac = Hmac::<sha2::Sha256>::new_from_slice(key).map_err(|_| Error::Crypto)?;
    mac.update(value);
    Ok(mac
        .finalize()
        .into_bytes()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect())
}
pub(super) fn external_hash(master: &[u8; 32], external: &ExternalChat) -> Result<String> {
    if external.provider != "codex" || external.id.is_empty() || external.id.len() > 512 {
        return Err(Error::Invalid(
            "External chat must identify a Codex thread.",
        ));
    }
    let index = crypto::hkdf_sha256(master, &[], b"openmates-task-external-chat-index-v1")?;
    hmac(
        &index,
        format!("{}\0{}", external.provider, external.id).as_bytes(),
    )
}
pub(super) fn decrypt(
    raw: Value,
    _master: &[u8; 32],
    wrapping: &[u8; 32],
    team: Option<&str>,
) -> Result<Resolved> {
    if raw["source"] == "workflow_run" {
        let id = string(&raw, "task_id")?;
        let stable = raw["workflow_run_id"].as_str().unwrap_or(id);
        let short = raw["short_id"]
            .as_str()
            .map(str::to_owned)
            .unwrap_or_else(|| format!("WF-{}", hash(stable)[..6].to_uppercase()));
        let mut public = raw.clone();
        public["short_id"] = json!(short);
        public["read_only"] = json!(true);
        return Ok(Resolved {
            raw,
            public,
            key: zeroize::Zeroizing::new([0; 32]),
        });
    }
    let wrappers = raw["key_wrappers"].as_array();
    let candidates = wrappers
        .into_iter()
        .flatten()
        .filter(|row| {
            if let Some(team) = team {
                row["key_type"] == "team"
                    && row["hashed_team_id"] == hash(team)
                    && row["team_key_epoch"] == 1
            } else {
                row["key_type"] == "master"
            }
        })
        .collect::<Vec<_>>();
    if let Some(team) = team {
        if raw["hashed_team_id"]
            .as_str()
            .is_some_and(|v| v != hash(team))
            || candidates.len() != 1
        {
            return Err(Error::Forbidden);
        }
    } else if raw["hashed_team_id"]
        .as_str()
        .is_some_and(|v| !v.is_empty())
        || wrappers
            .into_iter()
            .flatten()
            .any(|w| w["key_type"] == "team")
    {
        return Err(Error::Forbidden);
    }
    if candidates.len() > 1 {
        return Err(Error::Forbidden);
    }
    let encrypted = if let Some(wrapper) = candidates.first() {
        if wrapper["hashed_task_id"]
            .as_str()
            .is_some_and(|v| raw["task_id"].as_str().is_none_or(|id| v != hash(id)))
            || wrapper["expires_at"]
                .as_u64()
                .is_some_and(|expires| expires <= now())
        {
            return Err(Error::Forbidden);
        }
        string(wrapper, "encrypted_task_key")?
    } else if team.is_none() {
        string(&raw, "encrypted_task_key")?
    } else {
        return Err(Error::Forbidden);
    };
    let key = key_bytes(&crypto::decrypt_bytes(encrypted, wrapping)?)?;
    decode_with_key(raw, key)
}
pub(super) fn decode_with_key(raw: Value, key: Key) -> Result<Resolved> {
    let id = string(&raw, "task_id")?;
    let text = |field: &str| text(&raw, field, &key);
    let labels = arrays(&text(if raw["encrypted_labels"].is_string() {
        "encrypted_labels"
    } else {
        "encrypted_tags"
    })?)?;
    let short = raw["short_id"]
        .as_str()
        .map(str::to_owned)
        .unwrap_or_else(|| {
            format!(
                "{}-{}",
                raw["short_id_prefix"].as_str().unwrap_or("TASK"),
                u16::from_str_radix(&hash(id)[..4], 16).unwrap_or(0) as u32 % 10000
            )
        });
    let projects = arrays(&text("encrypted_linked_project_ids")?)?;
    let projects = if projects.is_empty() {
        raw["linked_project_ids"]
            .as_array()
            .cloned()
            .unwrap_or_default()
    } else {
        projects.into_iter().map(Value::String).collect()
    };
    let external = if raw["external_chat_provider"].is_string()
        && raw["encrypted_external_chat_id"].is_string()
    {
        json!({"provider":raw["external_chat_provider"],"id":text("encrypted_external_chat_id")?,"title":text("encrypted_external_chat_title")?})
    } else {
        Value::Null
    };
    let priority = raw["priority"].as_u64().unwrap_or(0);
    if priority > 4 {
        return Err(Error::Protocol);
    }
    let mut public = json!({"task_id":id,"short_id":short,"slug":text("encrypted_slug")?,"title":text("encrypted_title")?,"description":text("encrypted_description")?,"labels":labels,"tags":labels,"latest_instruction":text("encrypted_latest_instruction")?,"blocked_reason":text("encrypted_blocked_reason")?,"external_chat":external,"linked_project_ids":projects,"priority_level":(["none","low","medium","high","urgent"][priority as usize])});
    for field in [
        "status",
        "assignee_type",
        "assignee_identity",
        "assignee_hash",
        "primary_chat_id",
        "plan_id",
        "due_at",
        "priority",
        "position",
        "queue_state",
        "blocked_reason_code",
        "ai_execution_state",
        "version",
        "created_at",
        "updated_at",
    ] {
        public[field] = raw[field].clone();
    }
    Ok(Resolved { raw, public, key })
}
pub(super) fn text(raw: &Value, field: &str, key: &[u8; 32]) -> Result<String> {
    match raw.get(field) {
        None | Some(Value::Null) => Ok(String::new()),
        Some(Value::String(value)) if value.is_empty() => Ok(String::new()),
        Some(Value::String(value)) => crypto::decrypt_combined(value, key),
        _ => Err(Error::Protocol),
    }
}
pub(super) fn arrays(value: &str) -> Result<Vec<String>> {
    if value.is_empty() {
        return Ok(vec![]);
    }
    serde_json::from_str::<Vec<String>>(value).map_err(|_| Error::Crypto)
}
pub(super) fn encrypt_create(
    input: &TaskCreate,
    master: &[u8; 32],
    wrapping: &[u8; 32],
    team: Option<&str>,
) -> Result<Value> {
    if input.title.trim().is_empty()
        || input.title.len() > 100_000
        || input.description.len() > 1_000_000
    {
        return Err(Error::Invalid(
            "A Task title is required and private text must fit the supported limits.",
        ));
    }
    if input.primary_chat_id.is_some() && input.external_chat.is_some() {
        return Err(Error::Invalid(
            "A Task cannot bind native and external chats together.",
        ));
    }
    if team.is_some()
        && (input.primary_chat_id.is_some()
            || !input.linked_project_ids.is_empty()
            || input.plan_id.is_some()
            || input.external_chat.is_some())
    {
        return Err(Error::Invalid(
            "Linked contexts on new Team Tasks are not supported by the current protocol.",
        ));
    }
    let status = input.status.as_deref().unwrap_or("todo");
    validate_status(status)?;
    let priority = input.priority.unwrap_or(0);
    if priority > 4 {
        return Err(Error::Invalid("Task priority must be 0–4."));
    }
    let key = crypto::random_key();
    let id = input
        .task_id
        .clone()
        .unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
    uuid(&id)?;
    let now = now();
    let slug = crypto::normalize_object_slug(input.slug.as_deref().unwrap_or(&input.title))?;
    let labels = normalized_labels(&input.labels);
    let (kind, identity, assignee) = assignment(input.assign.as_deref())?;
    let wrapped = crypto::server_fields::encrypt_bytes(key.as_ref(), wrapping, &[])?;
    let mut value = json!({"task_id":id,"version":1,"encrypted_task_key":wrapped,"encrypted_title":crypto::server_fields::encrypt_text(input.title.trim(),&key, &[])?,"encrypted_description":crypto::server_fields::encrypt_text(&input.description,&key, &[])?,"encrypted_slug":crypto::server_fields::encrypt_text(&slug,&key, &[])?,"slug_lookup_hash":crypto::object_slug_lookup_hash(&slug,wrapping)?,"encrypted_labels":crypto::server_fields::encrypt_text(&serde_json::to_string(&labels)?,&key, &[])?,"encrypted_tags":crypto::server_fields::encrypt_text(&serde_json::to_string(&labels)?,&key, &[])?,"label_hashes":label_hashes(wrapping,&labels)?,"encrypted_linked_project_ids":crypto::server_fields::encrypt_text(&serde_json::to_string(&input.linked_project_ids)?,&key, &[])?,"linked_project_ids":input.linked_project_ids,"primary_chat_id":input.primary_chat_id,"plan_id":input.plan_id,"status":status,"priority":priority,"position":input.position.unwrap_or(now as i64),"created_at":now,"updated_at":now,"due_at":input.due_at,"assignee_type":kind,"assignee_identity":identity,"assignee_hash":assignee});
    if let Some(team) = team {
        value["team_id"] = json!(team);
        value["key_wrappers"] = json!([{"key_type":"team","hashed_team_id":hash(team),"team_key_epoch":1,"encrypted_task_key":wrapped,"created_at":now}]);
    }
    if let Some(external) = &input.external_chat {
        apply_external(&mut value, external, master, &key)?;
    }
    Ok(value)
}
pub(super) fn encrypt_patch(
    task: &Resolved,
    input: &TaskPatch,
    master: &[u8; 32],
    wrapping: &[u8; 32],
) -> Result<Value> {
    if task.public["read_only"] == true {
        return Err(Error::Invalid("Workflow projection Tasks are read-only."));
    }
    let key = &task.key;
    let mut value = json!({"version":task.raw["version"],"updated_at":now()});
    for (field, text) in [
        ("encrypted_title", &input.title),
        ("encrypted_description", &input.description),
    ] {
        if let Some(text) = text {
            if text.len() > 1_000_000 {
                return Err(Error::Invalid("Task text exceeds the supported limit."));
            }
            value[field] = json!(crypto::server_fields::encrypt_text(text, key, &[])?);
        }
    }
    if let Some(slug) = &input.slug {
        let slug = crypto::normalize_object_slug(slug)?;
        value["encrypted_slug"] = json!(crypto::server_fields::encrypt_text(&slug, key, &[])?);
        value["slug_lookup_hash"] = json!(crypto::object_slug_lookup_hash(&slug, wrapping)?);
    }
    if let Some(status) = &input.status {
        validate_status(status)?;
        value["status"] = json!(status);
    }
    if let Some(priority) = input.priority {
        if priority > 4 {
            return Err(Error::Invalid("Task priority must be 0–4."));
        }
        value["priority"] = json!(priority);
    }
    if let Some(assign) = &input.assign {
        let (kind, identity, assignee) = assignment(Some(assign))?;
        value["assignee_type"] = json!(kind);
        value["assignee_identity"] = json!(identity);
        value["assignee_hash"] = json!(assignee);
    }
    if let Some(due) = input.due_at {
        value["due_at"] = json!(due);
    }
    if let Some(plan) = &input.plan_id {
        value["plan_id"] = json!(plan);
    }
    if let Some(projects) = &input.linked_project_ids {
        value["linked_project_ids"] = json!(projects);
        value["encrypted_linked_project_ids"] = json!(crypto::server_fields::encrypt_text(
            &serde_json::to_string(projects)?,
            key
        , &[])?);
    }
    if input.primary_chat_id.as_ref().is_some_and(|c| c.is_some())
        && input.external_chat.as_ref().is_some_and(|c| c.is_some())
    {
        return Err(Error::Invalid(
            "A Task cannot bind native and external chats together.",
        ));
    }
    if let Some(chat) = &input.primary_chat_id {
        value["primary_chat_id"] = json!(chat);
        for field in [
            "external_chat_provider",
            "external_chat_lookup_hash",
            "encrypted_external_chat_id",
            "encrypted_external_chat_title",
        ] {
            value[field] = Value::Null;
        }
    }
    if let Some(external) = &input.external_chat {
        if let Some(external) = external {
            value["primary_chat_id"] = Value::Null;
            apply_external(&mut value, external, master, key)?;
        } else {
            for field in [
                "external_chat_provider",
                "external_chat_lookup_hash",
                "encrypted_external_chat_id",
                "encrypted_external_chat_title",
            ] {
                value[field] = Value::Null;
            }
        }
    }
    if input.labels.is_some() || !input.add_labels.is_empty() || !input.remove_labels.is_empty() {
        let base = if let Some(labels) = &input.labels {
            labels.clone()
        } else {
            task.public["labels"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
                .map(str::to_owned)
                .collect()
        };
        let remove = normalized_labels(&input.remove_labels);
        let mut labels = normalized_labels(&base)
            .into_iter()
            .filter(|label| !remove.contains(label))
            .collect::<Vec<_>>();
        labels.extend(input.add_labels.iter().cloned());
        let labels = normalized_labels(&labels);
        let encrypted = crypto::server_fields::encrypt_text(&serde_json::to_string(&labels)?, key, &[])?;
        value["encrypted_labels"] = json!(encrypted);
        value["encrypted_tags"] = json!(encrypted);
        value["label_hashes"] = json!(label_hashes(wrapping, &labels)?);
    }
    Ok(value)
}
fn apply_external(
    value: &mut Value,
    external: &ExternalChat,
    master: &[u8; 32],
    key: &[u8; 32],
) -> Result<()> {
    value["external_chat_provider"] = json!(external.provider);
    value["external_chat_lookup_hash"] = json!(external_hash(master, external)?);
    value["encrypted_external_chat_id"] = json!(crypto::server_fields::encrypt_text(&external.id, key, &[])?);
    value["encrypted_external_chat_title"] = json!(crypto::server_fields::encrypt_text(&external.title, key, &[])?);
    Ok(())
}
pub(super) fn assignment(
    value: Option<&str>,
) -> Result<(&'static str, Option<&'static str>, Option<String>)> {
    match value.unwrap_or("user") {
        "" | "user" => Ok(("user", None, None)),
        "openmates" => Ok(("openmates", Some("openmates"), None)),
        "codex" | "external_ai" | "external-ai" => Ok(("external_ai", Some("codex"), None)),
        "unassigned" => Ok(("unassigned", None, None)),
        hash if hash.len() == 64 && hash.bytes().all(|b| b.is_ascii_hexdigit()) => {
            Ok(("user", None, Some(hash.to_owned())))
        }
        _ => Err(Error::Invalid("Invalid Task assignee.")),
    }
}
pub(super) fn validate_status(status: &str) -> Result<()> {
    if ["backlog", "todo", "in_progress", "blocked", "done"].contains(&status) {
        Ok(())
    } else {
        Err(Error::Invalid("Invalid Task status."))
    }
}
pub(super) fn aad_encrypt(text: &str, key: &[u8; 32], aad: &str) -> Result<String> {
    crypto::server_fields::encrypt_text(text, key, aad.as_bytes())
}
pub(super) fn aad_decrypt(ciphertext: &str, key: &[u8; 32], aad: &str) -> Result<String> {
    // Retain this field's strict UTF-8 policy and accepted old native frames.
    let plain=crypto::server_fields::decrypt_bytes(ciphertext,key,aad.as_bytes())?;
    String::from_utf8(plain.to_vec()).map_err(|_|Error::Crypto)
}
pub(super) fn activity(task: &Resolved, raw: &Value) -> Result<Value> {
    let mut value = json!({});
    for field in [
        "entry_id",
        "task_id",
        "kind",
        "actor_type",
        "actor_hash",
        "actor_identity",
        "event_type",
        "actor_display_name",
        "actor_profile_image_url",
        "source_surface",
        "created_at",
        "deleted_at",
        "deleted_by_hash",
        "deleted_by_display_name",
        "previous_status",
        "next_status",
    ] {
        if let Some(v) = raw.get(field) {
            value[field] = v.clone();
        }
    }
    value["author_hash"] = raw.get("author_hash").unwrap_or(&raw["actor_hash"]).clone();
    value["embed_refs"] = if raw["kind"] == "tombstone" {
        json!([])
    } else {
        raw["embed_refs"].clone()
    };
    if raw["kind"] == "comment" {
        let task_id = string(&task.raw, "task_id")?;
        let entry = string(raw, "entry_id")?;
        value["message"] = json!(aad_decrypt(
            string(raw, "encrypted_message")?,
            &task.key,
            &format!("task_activity_comment:{task_id}:{entry}:v1")
        )?);
        if let Some(encrypted) = raw["encrypted_embed_key_material"].as_str() {
            value["embed_key_material"] = json!(aad_decrypt(
                encrypted,
                &task.key,
                &format!("task_activity_embed_keys:{task_id}:{entry}:v1")
            )?);
        }
    }
    Ok(value)
}

#[cfg(all(test,not(target_arch="wasm32")))]
#[path="field_interop_support.rs"]
pub(super) mod field_interop_support;
#[cfg(all(test,not(target_arch="wasm32")))]
mod field_interop_tests {
    use super::*;
    use field_interop_support::{case,assert_web};
    #[test]
    fn actual_task_create_patch_and_activity_read_in_web_legacy_decoders_without_export(){
        let master=[7;32];
        let input=TaskCreate{title:"Synthetic Task ✓".into(),description:"Private task description".into(),..Default::default()};
        let created=encrypt_create(&input,&master,&master,None).unwrap();
        let task=decrypt(created.clone(),&master,&master,None).unwrap();
        let mut rows=vec![case("task-key","master-binary",created["encrypted_task_key"].as_str().unwrap(),&master,task.key.as_ref(),""),case("task-title","object-text",created["encrypted_title"].as_str().unwrap(),&task.key,input.title.as_bytes(),""),case("task-description","object-text",created["encrypted_description"].as_str().unwrap(),&task.key,input.description.as_bytes(),"")];
        let patch=encrypt_patch(&task,&TaskPatch{title:Some("Updated Task 界".into()),description:Some("".into()),..Default::default()},&master,&master).unwrap();
        rows.push(case("task-patch-title","object-text",patch["encrypted_title"].as_str().unwrap(),&task.key,"Updated Task 界".as_bytes(),""));
        rows.push(case("task-empty-description","object-text",patch["encrypted_description"].as_str().unwrap(),&task.key,b"",""));
        for kind in ["task_activity_comment","task_activity_embed_keys"] {
            let aad=format!("{kind}:22222222-2222-4222-8222-222222222222:33333333-3333-4333-8333-333333333333:v1");
            let encrypted=aad_encrypt("Synthetic private activity ✓",&task.key,&aad).unwrap();
            rows.push(case(kind,"object-text",&encrypted,&task.key,"Synthetic private activity ✓".as_bytes(),&aad));
        }
        assert_web(rows);
    }
    #[test]
    fn activity_reads_preserve_old_native_frames_exact_aad_and_strict_utf8(){
        use base64::{Engine,engine::general_purpose::STANDARD};
        let key=[7;32];let iv=[3;12];let aad=b"task_activity_comment:task:entry:v1";
        let mut old=b"OM".to_vec();old.extend(crypto::key_fingerprint(&key));old.extend(iv);old.extend(crypto::encrypt_aead(b"Synthetic old activity",&key,&iv,aad).unwrap());
        assert_eq!(aad_decrypt(&STANDARD.encode(&old),&key,std::str::from_utf8(aad).unwrap()).unwrap(),"Synthetic old activity");
        assert!(aad_decrypt(&STANDARD.encode(&old),&key,"wrong-scope").is_err());
        let invalid=crypto::server_fields::encrypt_bytes(&[0xff],&key,aad).unwrap();
        assert!(aad_decrypt(&invalid,&key,std::str::from_utf8(aad).unwrap()).is_err());
    }
}
