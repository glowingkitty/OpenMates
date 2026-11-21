//! Project presentation (description, icon, category): normalisation, write rules and sync.
//!
//! Shared core for every shell (CLI/TUI, web Worker via `web_projects::presentation`, Apple).
//! Decides which presentation fields an origin may write (creation, specification approval,
//! backfill, user) and encrypts them with the Project key like `encrypted_name`.
//! Contract: `docs/plans/project-presentation/contract.md`; spec `projects.presentation.*`.
use super::*;

/// Categories a Project may carry (the chat category ids, contract section 2).
pub const PRESENTATION_CATEGORIES: [&str; 16] = [
    "software_development",
    "business_development",
    "medical_health",
    "legal_law",
    "maker_prototyping",
    "marketing_sales",
    "finance",
    "design",
    "electrical_engineering",
    "movies_tv",
    "history",
    "science",
    "life_coach_psychology",
    "cooking_food",
    "activism",
    "general_knowledge",
];
/// Longest description in characters, including the closing ellipsis.
const MAX_PRESENTATION_DESCRIPTION: usize = 140;
const MAX_ICON_CHARS: usize = 40;
const LEGACY_ICON: &str = "folder";

/// Who asks for a presentation write (contract section 4).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PresentationOrigin {
    /// Assistant-created Project.
    Creation,
    /// The Project's specification was approved (refreshes once).
    SpecificationApproval,
    /// One-time fill of a legacy Project that has items.
    Backfill,
    /// The user typed or picked a value; never refused.
    User,
}

/// Who wrote a presentation field last.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PresentationSource {
    /// Written from an assistant proposal.
    Assistant,
    /// Filled by the one-time backfill.
    Backfill,
    /// Typed by the user, or present before this feature existed.
    User,
}

/// Per-field write sources; an absent source means never written.
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct PresentationSources {
    /// Source of the description.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<PresentationSource>,
    /// Source of the icon.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub icon: Option<PresentationSource>,
    /// Source of the category.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub category: Option<PresentationSource>,
}

/// The decrypted `encrypted_presentation_state` JSON (contract section 3).
/// A missing state is [`PresentationState::default`] semantically, but callers
/// keep `None` for "legacy Project" because backfill depends on the difference.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct PresentationState {
    /// Format version, 1.
    pub v: u32,
    /// Per-field sources.
    pub sources: PresentationSources,
    /// True once the specification approval refresh ran.
    pub specification_refreshed: bool,
    /// True once creation or backfill ran.
    pub backfilled: bool,
}

impl Default for PresentationState {
    fn default() -> Self {
        Self {
            v: 1,
            sources: PresentationSources::default(),
            specification_refreshed: false,
            backfilled: false,
        }
    }
}

/// Presentation values to write or proposed; `None` means "not given".
#[derive(Clone, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct PresentationFields {
    /// One-line description (`Some("")` clears it for the user origin).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    /// Lucide icon name, kebab case.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub icon: Option<String>,
    /// One of [`PRESENTATION_CATEGORIES`] (`Some("")` clears it for the user origin).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub category: Option<String>,
}

/// A model proposal for a Project (response of the suggest route).
pub type ProjectPresentationProposal = PresentationFields;

impl PresentationFields {
    /// Reads `{description, icon, category}`; null/absent fields are `None`.
    ///
    /// # Errors
    /// A message naming the field when it is neither string nor null.
    pub fn from_json(value: &Value) -> std::result::Result<Self, String> {
        let field = |name: &str| match &value[name] {
            Value::Null => Ok(None),
            Value::String(text) => Ok(Some(text.clone())),
            _ => Err(format!("{name}_not_text")),
        };
        Ok(Self {
            description: field("description")?,
            icon: field("icon")?,
            category: field("category")?,
        })
    }
}

/// The Project's current stored values; empty string means unset.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct PresentationValues {
    /// Current description.
    pub description: String,
    /// Current icon (`folder` is the legacy default).
    pub icon: String,
    /// Current category.
    pub category: String,
}

impl PresentationValues {
    /// Reads the three values from a decoded public Project (or the web op input).
    pub fn from_json(value: &Value) -> Self {
        let text = |name: &str| value[name].as_str().unwrap_or_default().to_owned();
        Self {
            description: text("description"),
            icon: text("icon"),
            category: text("category"),
        }
    }
}

/// One chat of a Project as input of [`dominant_category`].
#[derive(Clone, Debug, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct PresentationChat {
    /// Chat category id, when categorised.
    #[serde(default)]
    pub category: Option<String>,
    /// Last update time; the newest wins a tie.
    #[serde(default)]
    pub updated_at: u64,
}

/// Result of [`plan_write`]: the values to encrypt and the new state.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct PresentationWrite {
    /// Only the fields to write.
    pub fields: PresentationFields,
    /// The state to store with them.
    pub state: PresentationState,
}

/// Collapses a description to one line and cuts it at a word boundary to 140
/// characters with a closing `…`.
pub fn normalize_description(text: &str) -> String {
    let line = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if line.chars().count() <= MAX_PRESENTATION_DESCRIPTION {
        return line;
    }
    let head: String = line
        .chars()
        .take(MAX_PRESENTATION_DESCRIPTION - 1)
        .collect();
    let mid_word = line
        .chars()
        .nth(MAX_PRESENTATION_DESCRIPTION - 1)
        .is_some_and(|c| !c.is_whitespace());
    let cut = match head.rfind(' ') {
        Some(at) if mid_word => &head[..at],
        _ => head.as_str(),
    };
    format!("{}…", cut.trim_end())
}

/// Lowercased icon name when it is valid kebab case (at most 40 characters).
pub fn normalize_icon(text: &str) -> Option<String> {
    let icon = text.trim().to_lowercase();
    let valid = !icon.is_empty()
        && icon.chars().count() <= MAX_ICON_CHARS
        && icon.split('-').all(|part| {
            !part.is_empty()
                && part
                    .chars()
                    .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit())
        });
    valid.then_some(icon)
}

/// The category when it is one of [`PRESENTATION_CATEGORIES`].
pub fn normalize_category(text: &str) -> Option<String> {
    let category = text.trim().to_lowercase();
    PRESENTATION_CATEGORIES
        .contains(&category.as_str())
        .then_some(category)
}

/// Normalises a proposal: invalid icon/category are dropped; an empty
/// description or category stays `Some("")` (a clear, honoured only for `user`).
pub fn normalize(proposal: &PresentationFields) -> PresentationFields {
    let blank = |t: &String| t.trim().is_empty();
    PresentationFields {
        description: proposal.description.as_deref().map(normalize_description),
        icon: proposal.icon.as_deref().and_then(normalize_icon),
        category: proposal
            .category
            .as_ref()
            .and_then(|c| blank(c).then(String::new).or_else(|| normalize_category(c))),
    }
}

/// The category most chats share; a tie goes to the most recently updated chat
/// among the tied categories. `None` when no chat has a category.
pub fn dominant_category(chats: &[PresentationChat]) -> Option<String> {
    let mut tally: Vec<(&str, usize, u64)> = vec![];
    for chat in chats {
        let Some(category) = chat
            .category
            .as_deref()
            .filter(|c| PRESENTATION_CATEGORIES.contains(c))
        else {
            continue;
        };
        match tally.iter_mut().find(|(name, _, _)| *name == category) {
            Some(entry) => {
                entry.1 += 1;
                entry.2 = entry.2.max(chat.updated_at);
            }
            None => tally.push((category, 1, chat.updated_at)),
        }
    }
    tally
        .into_iter()
        .max_by_key(|(_, count, newest)| (*count, *newest))
        .map(|(name, _, _)| name.to_owned())
}

fn non_empty(value: &Option<String>) -> Option<String> {
    value.clone().filter(|v| !v.is_empty())
}

/// Decides what `origin` may write (contract section 4); `None` means no write.
///
/// `state` is `None` for a legacy Project. For `user` a present proposal field
/// counts as changed (even empty); for other origins only non-empty values do.
pub fn plan_write(
    origin: PresentationOrigin,
    state: Option<&PresentationState>,
    current: &PresentationValues,
    proposal: &PresentationFields,
    item_count: usize,
    chats: &[PresentationChat],
) -> Option<PresentationWrite> {
    let proposal = normalize(proposal);
    let mut next = state.cloned().unwrap_or_default();
    let mut fields = PresentationFields::default();
    match origin {
        PresentationOrigin::Creation => {
            fields.description = non_empty(&proposal.description);
            fields.icon = proposal.icon.clone();
            fields.category = non_empty(&proposal.category);
            next.sources = sources_for(&fields, PresentationSource::Assistant, next.sources);
            next.backfilled = true;
            next.specification_refreshed = false;
        }
        PresentationOrigin::SpecificationApproval => {
            if next.specification_refreshed {
                return None;
            }
            let locked = |s: Option<PresentationSource>| s == Some(PresentationSource::User);
            if !locked(next.sources.description) {
                fields.description = non_empty(&proposal.description);
            }
            if !locked(next.sources.icon) {
                fields.icon = proposal.icon.clone();
            }
            if !locked(next.sources.category) {
                fields.category = non_empty(&proposal.category);
            }
            next.sources = sources_for(&fields, PresentationSource::Assistant, next.sources);
            next.specification_refreshed = true;
        }
        PresentationOrigin::Backfill => {
            if state.is_some() || item_count == 0 {
                return None;
            }
            let icon_unset = current.icon.is_empty() || current.icon == LEGACY_ICON;
            if current.description.is_empty() {
                fields.description = non_empty(&proposal.description);
            }
            if icon_unset {
                fields.icon = proposal.icon.clone();
            }
            if current.category.is_empty() {
                fields.category =
                    dominant_category(chats).or_else(|| non_empty(&proposal.category));
            }
            // Values typed before this feature count as the user's and stay locked.
            let mut sources = PresentationSources::default();
            if !current.description.is_empty() {
                sources.description = Some(PresentationSource::User);
            }
            if !icon_unset {
                sources.icon = Some(PresentationSource::User);
            }
            if !current.category.is_empty() {
                sources.category = Some(PresentationSource::User);
            }
            next.sources = sources_for(&fields, PresentationSource::Backfill, sources);
            next.backfilled = true;
        }
        PresentationOrigin::User => {
            fields.description = proposal.description.clone();
            fields.icon = proposal.icon.clone();
            fields.category = proposal.category.clone();
            if fields == PresentationFields::default() {
                return None;
            }
            next.sources = sources_for(&fields, PresentationSource::User, next.sources);
        }
    }
    Some(PresentationWrite {
        fields,
        state: next,
    })
}

fn sources_for(
    fields: &PresentationFields,
    source: PresentationSource,
    mut sources: PresentationSources,
) -> PresentationSources {
    if fields.description.is_some() {
        sources.description = Some(source);
    }
    if fields.icon.is_some() {
        sources.icon = Some(source);
    }
    if fields.category.is_some() {
        sources.category = Some(source);
    }
    sources
}

/// Reads the decoded `presentation_state` of a public Project.
///
/// # Errors
/// `Error::Protocol` when the stored JSON is not a presentation state.
pub fn state_from_public(public: &Value) -> Result<Option<PresentationState>> {
    match &public["presentation_state"] {
        Value::Null => Ok(None),
        value => serde_json::from_value(value.clone())
            .map(Some)
            .map_err(|_| Error::Protocol),
    }
}

/// Adds the encrypted presentation fields of `write` to a PATCH `payload`.
fn put_write(payload: &mut Value, write: &PresentationWrite, key: &[u8; 32]) -> Result<()> {
    let fields = [
        ("description", &write.fields.description),
        ("icon", &write.fields.icon),
        ("category", &write.fields.category),
    ];
    for (name, value) in fields {
        if let Some(text) = value {
            payload[format!("encrypted_{name}")] =
                json!(crypto::server_fields::encrypt_text(text, key, &[])?);
        }
    }
    payload["encrypted_presentation_state"] = json!(crypto::server_fields::encrypt_text(
        &serde_json::to_string(&write.state)?,
        key,
        &[]
    )?);
    Ok(())
}

impl Projects<'_> {
    /// For `update()`: replaces the raw description/icon/category of `patch` by the
    /// normalised `user` plan and adds the encrypted category and state.
    pub(super) fn merge_user_presentation(
        &self,
        project: &ResolvedProject,
        input: &ProjectPatch,
        patch: &mut Value,
    ) -> Result<()> {
        if input.description.is_none() && input.icon.is_none() && input.category.is_none() {
            return Ok(());
        }
        let proposal = PresentationFields {
            description: input.description.clone(),
            icon: input.icon.clone(),
            category: input.category.clone(),
        };
        let state = state_from_public(&project.public)?;
        let current = PresentationValues::from_json(&project.public);
        if let Some(write) = plan_write(
            PresentationOrigin::User,
            state.as_ref(),
            &current,
            &proposal,
            0,
            &[],
        ) {
            put_write(patch, &write, &project.key)?;
        }
        Ok(())
    }

    /// PATCHes a prepared payload and returns the updated public Project.
    pub(super) async fn send_patch_with_history(
        &mut self,
        project: ResolvedProject,
        patch: Value,
    ) -> Result<Value> {
        let route = self.path(
            &format!("/v1/projects/{}", string(&project.raw, "project_id")?),
            &[],
        );
        let data = self
            .backend
            .request(Method::PATCH, &route, Some(patch), None)
            .await?;
        if data["project"]["project_id"] != project.raw["project_id"] {
            return Err(Error::Forbidden);
        }
        let mut merged = project.raw.clone();
        if let (Some(row), Some(updated)) = (merged.as_object_mut(), data["project"].as_object()) {
            row.extend(updated.iter().map(|(k, v)| (k.clone(), v.clone())));
        }
        let mut public = decode(merged, project.key)?.public;
        if let Some(history) = data.get("history") {
            public["history"] = history.clone();
        }
        Ok(public)
    }

    /// Applies `proposal` for `origin` to the Project: resolves it, plans the
    /// write and PATCHes the encrypted fields and state with the row version.
    ///
    /// Returns the updated public Project, or `None` when the rules say nothing
    /// is to be written. `item_count` and `chats` feed the backfill rules.
    ///
    /// # Errors
    /// Transport or crypto errors; `Error::Protocol` for a stored state that is not
    /// presentation JSON.
    pub async fn apply_presentation(
        &mut self,
        project_ref: &str,
        origin: PresentationOrigin,
        proposal: &PresentationFields,
        item_count: usize,
        chats: &[PresentationChat],
    ) -> Result<Option<Value>> {
        let project = self.resolve(project_ref).await?;
        let state = state_from_public(&project.public)?;
        let current = PresentationValues::from_json(&project.public);
        let Some(write) = plan_write(
            origin,
            state.as_ref(),
            &current,
            proposal,
            item_count,
            chats,
        ) else {
            return Ok(None);
        };
        let mut patch = json!({"updated_at": now()});
        if let Some(version) = project.raw["version"].as_u64() {
            patch["version"] = json!(version);
        }
        put_write(&mut patch, &write, &project.key)?;
        self.send_patch_with_history(project, patch).await.map(Some)
    }

    /// Asks the server for a presentation proposal (`POST /v1/projects/presentation/suggest`,
    /// contract section 7). Stores nothing; the result is normalised.
    ///
    /// # Errors
    /// Transport errors; `Error::Protocol` when the response has no `presentation` object.
    pub async fn suggest_presentation(
        &mut self,
        body: Value,
    ) -> Result<ProjectPresentationProposal> {
        let route = self.path("/v1/projects/presentation/suggest", &[]);
        let data = self
            .backend
            .request(Method::POST, &route, Some(body), None)
            .await?;
        let proposal =
            PresentationFields::from_json(&data["presentation"]).map_err(|_| Error::Protocol)?;
        if !data["presentation"].is_object() {
            return Err(Error::Protocol);
        }
        Ok(normalize(&proposal))
    }

    /// Refreshes the presentation once after the Project's specification was
    /// approved: suggests from the specification, then applies with origin
    /// `specification_approval`. Skips the network call when already refreshed.
    ///
    /// # Errors
    /// Errors of [`Self::suggest_presentation`] and [`Self::apply_presentation`].
    pub async fn refresh_after_specification_approval(
        &mut self,
        project_ref: &str,
        title: &str,
        summary: &str,
    ) -> Result<Option<Value>> {
        let project = self.resolve(project_ref).await?;
        if state_from_public(&project.public)?.is_some_and(|s| s.specification_refreshed) {
            return Ok(None);
        }
        let body = json!({
            "purpose": "specification_approval",
            "name": project.public["name"],
            "description": project.public["description"],
            "specification": {"title": title, "summary": summary},
            "chat_titles": [],
            "item_names": [],
        });
        let proposal = self.suggest_presentation(body).await?;
        let id = string(&project.public, "project_id")?.to_owned();
        self.apply_presentation(
            &id,
            PresentationOrigin::SpecificationApproval,
            &proposal,
            0,
            &[],
        )
        .await
    }
}
