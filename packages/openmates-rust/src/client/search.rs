//! Cookie-session chat search matches the existing metadata-only client policy.
//! Queries and decrypted results remain caller-owned memory, never sync cache.
use super::*;

impl Client {
    /// Search saved-chat metadata in the selected Personal or Team context.
    /// Matches title, summary, category, mate name and ID, not message bodies,
    /// slugs or draft previews. Results use the legacy ChatListItem JSON shape.
    /// API-key clients are a separate surface and never inherit this session.
    /// Coverage is the existing phased-sync metadata window (currently recent
    /// 100 chats plus discovered drafts), not a full-account search or retained
    /// inventory of older cached chats. Full census/pagination is not ported.
    pub async fn search_chats(&mut self, query: &str) -> Result<Vec<Value>> {
        let normalized = query.trim_matches(js_whitespace).to_lowercase();
        if normalized.is_empty() {
            return Err(Error::Invalid("Enter a nonempty chat search query."));
        }
        self.require_session()?;
        let generation = self.generation;
        let cancel = self.operation_cancel.clone();
        let current = |client: &Self| {
            if cancel.is_cancelled() || client.generation != generation {
                Err(Error::Cancelled)
            } else {
                Ok(())
            }
        };
        current(self)?;
        self.refresh_chat_metadata(0).await?;
        current(self)?;
        let mut rows: Vec<Value> = self.chats.values().cloned().collect();
        if self.team()?.is_some() {
            // Phase 2 metadata intentionally carries no key wrappers. Obtain
            // existing, authorized Team wrappers without fetching transcripts
            // or treating a Personal wrapper as a Team key.
            let mut hydrated = vec![];
            for batch in rows.chunks(100) {
                current(self)?;
                let ids: BTreeMap<&str, &Value> = batch
                    .iter()
                    .map(|row| Ok((required(row, "id")?, row)))
                    .collect::<Result<_>>()?;
                let path = self.scoped("/v1/chats/metadata/batch")?;
                let response = self
                    .request(
                        Method::POST,
                        &path,
                        Some(json!({"chat_ids":ids.keys().collect::<Vec<_>>()})),
                    )
                    .await?;
                current(self)?;
                let mut seen = std::collections::BTreeSet::new();
                for row in response["chats"].as_array().ok_or(Error::Protocol)? {
                    let id = required(row, "id")?;
                    let original = ids.get(id).ok_or(Error::Forbidden)?;
                    if !seen.insert(id) || row["team_id"].as_str() != self.team()? {
                        return Err(Error::Forbidden);
                    }
                    let mut merged = (*original).clone();
                    for field in [
                        "chat_key_wrappers",
                        "encrypted_chat_key",
                        "chat_visibility",
                        "participant_user_hashes",
                        "team_id",
                    ] {
                        merged[field] = row[field].clone();
                    }
                    hydrated.push(merged);
                }
                // Omitted rows were deleted or became out of scope. Their
                // previously cached metadata must not become search results.
            }
            rows = hydrated;
        }
        current(self)?;
        rows.sort_by(|a, b| {
            numeric(&b["last_edited_overall_timestamp"])
                .unwrap_or(0.0)
                .total_cmp(&numeric(&a["last_edited_overall_timestamp"]).unwrap_or(0.0))
        });
        let wrapping = self.cached_wrapping_key()?;
        let mut results = vec![];
        for row in rows {
            current(self)?;
            let result = self.search_chat_row(&row, &wrapping)?;
            if matches_query(&result, &normalized) {
                results.push(result);
            }
        }
        current(self)?;
        Ok(results)
    }

    fn search_chat_row(&self, row: &Value, wrapping: &[u8; 32]) -> Result<Value> {
        let id = required(row, "id")?;
        let team = self.team()?;
        // A foreign scope is not a locked row. Never expose even its ID.
        for (field, expected) in [
            ("team_id", team.map(str::to_owned)),
            ("hashed_team_id", team.map(sha256)),
        ] {
            if let Some(actual) = row
                .get(field)
                .and_then(Value::as_str)
                .filter(|v| !v.is_empty())
                && Some(actual) != expected.as_deref()
            {
                return Err(Error::Forbidden);
            }
        }
        if text(row, "chat_visibility") == "direct" {
            let owner = text(&self.user, "id");
            let participants = row["participant_user_hashes"]
                .as_array()
                .ok_or(Error::Forbidden)?;
            if team.is_none()
                || owner.is_empty()
                || participants.len() != 2
                || participants[0] == participants[1]
                || !participants.iter().all(Value::is_string)
                || !participants
                    .iter()
                    .any(|p| p.as_str() == Some(sha256(owner).as_str()))
            {
                return Err(Error::Forbidden);
            }
        }
        let key = match self.chat_key(row, wrapping) {
            Ok(key) => Some(key),
            Err(Error::Crypto | Error::Forbidden) => None,
            Err(Error::Protocol)
                if text(row, "encrypted_chat_key").is_empty()
                    && row["chat_key_wrappers"]
                        .as_array()
                        .is_none_or(Vec::is_empty) =>
            {
                None
            }
            Err(error) => return Err(error),
        };
        let locked = !text(row, "encrypted_chat_key").is_empty() && key.is_none();
        let field = |name| key.as_deref().and_then(|key| decrypted(row, name, key));
        let title = field("encrypted_title");
        let summary = field("encrypted_chat_summary");
        let category = field("encrypted_category");
        let has_draft = !text(row, "encrypted_draft_md").is_empty();
        let preview = if !locked && has_draft {
            let master = &self.require_session()?.master_key;
            decrypted(row, "encrypted_draft_preview", master)
                .filter(|v| !v.is_empty())
                .or_else(|| decrypted(row, "encrypted_draft_md", master))
                .map(|text| draft_preview(&text))
                .filter(|v| !v.is_empty())
        } else {
            None
        };
        let slug = if key.is_some() && row["encrypted_slug"].is_string() {
            Some(field("encrypted_slug").unwrap_or_default())
        } else {
            None
        };
        let mut result = json!({"id":id,"shortId":id.chars().take(8).collect::<String>(),
            "chatVisibility":if text(row,"chat_visibility")=="direct" {"direct"} else if team.is_some() {"team"} else {"personal"},
            "slug":slug,"title":title,"summary":summary,
            "createdAt":number_or_null(&row["created_at"]),"updatedAt":number_or_null(&row["last_edited_overall_timestamp"]),
            "category":category,"mateName":category.as_deref().and_then(mate_name),
            "parentId":row["parent_id"].as_str(),"isSubChat":row["is_sub_chat"]==true,
            "isHiddenCandidate":locked || (key.is_none() && preview.is_none()),
            "isHidden":row["is_hidden"]==true,"pinned":row["pinned"]==true,
            "hasDraft":has_draft,"draftPreview":preview,"metadataUpdatedAt":metadata_timestamp(&row["updated_at"])});
        if let Some(focus) = field("encrypted_active_focus_id").filter(|v| !v.is_empty()) {
            result["activeFocusId"] = json!(focus);
        }
        if let Some(participants) = row["participant_user_hashes"].as_array() {
            result["participantUserHashes"] = json!(
                participants
                    .iter()
                    .filter_map(Value::as_str)
                    .collect::<Vec<_>>()
            );
        }
        Ok(result)
    }
}
fn numeric(value: &Value) -> Option<f64> {
    value.as_f64().filter(|n| n.is_finite())
}
fn number_or_null(value: &Value) -> Value {
    if value.is_number() {
        value.clone()
    } else {
        Value::Null
    }
}
fn metadata_timestamp(value: &Value) -> f64 {
    let n = numeric(value)
        .or_else(|| value.as_str()?.trim().parse::<f64>().ok())
        .unwrap_or(0.0);
    if !n.is_finite() || n <= 0.0 {
        0.0
    } else if n > 10_000_000_000.0 {
        (n / 1000.0).floor()
    } else {
        n.floor()
    }
}
fn decrypted(row: &Value, field: &str, key: &[u8; 32]) -> Option<String> {
    crypto::decrypt_combined(row[field].as_str()?, key).ok()
}
fn matches_query(row: &Value, query: &str) -> bool {
    ["title", "summary", "category", "mateName"]
        .iter()
        .any(|field| {
            row[*field]
                .as_str()
                .is_some_and(|v| v.to_lowercase().contains(query))
        })
        || text(row, "id").contains(query)
}
fn draft_preview(value: &str) -> String {
    // JS whitespace normalization; preserve well-formed UTF-8 at the 200 UTF-16
    // unit boundary instead of synthesizing a dangling surrogate.
    let collapsed = value
        .split(js_whitespace)
        .filter(|v| !v.is_empty())
        .collect::<Vec<_>>()
        .join(" ");
    let mut units = 0;
    collapsed
        .chars()
        .take_while(|c| {
            units += c.len_utf16();
            units <= 200
        })
        .collect()
}
pub(super) fn js_whitespace(c: char) -> bool {
    matches!(c,'\u{0009}'..='\u{000d}'|'\u{0020}'|'\u{00a0}'|'\u{1680}'|'\u{2000}'..='\u{200a}'|'\u{2028}'|'\u{2029}'|'\u{202f}'|'\u{205f}'|'\u{3000}'|'\u{feff}')
}
pub(super) fn mate_name(category: &str) -> Option<&'static str> {
    Some(match category {
        "software_development" => "Sophia",
        "business_development" => "Burton",
        "life_coach_psychology" => "Lisa",
        "medical_health" => "Melvin",
        "legal_law" => "Leon",
        "finance" => "Finn",
        "design" => "Denise",
        "marketing_sales" => "Mark",
        "science" => "Scarlett",
        "history" => "Hiro",
        "cooking_food" => "Colin",
        "electrical_engineering" => "Elton",
        "maker_prototyping" => "Makani",
        "movies_tv" => "Monika",
        "activism" => "Ace",
        "general_knowledge" => "George",
        "onboarding_support" => "Suki",
        _ => return None,
    })
}

#[cfg(test)]
#[path = "search_tests.rs"]
mod tests;
