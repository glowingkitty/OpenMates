//! Client half of embed adoption into a Project (shared core, P11).
//!
//! After a saved turn persisted its artifacts, `receive_turn` hands the
//! turn's adoption candidates (ids, types, parents, paths; never file text) to
//! [`Client::adopt_turn_embeds`] through the existing Project phase. When the
//! chat has an active Project focus, `work::Projects::adopt_turn` links the
//! finished application files, the application and the test results. Every
//! failure becomes a report row on the send outcome and never fails the turn.
//! The explicit repair path resolves an existing embed's key here
//! ([`Client::adoption_embed_source`]). Contract:
//! `docs/plans/cloud-project-development/contracts/project-embed-adoption.md`.
use super::plaintext::Plain;
use super::project_create_request::ProjectCreateState;
use super::transport::{send, wait};
use super::*;
use crate::work::{ProjectFilters, TurnEmbed};

/// Internal phase kind that carries the adoption candidates. No server frame
/// reaches the Project phase under this name: `receive_turn` only routes the
/// named server frames there.
pub(super) const TURN_ADOPTION_KIND: &str = "local_project_embed_adoption";

/// Reports kept per turn (one per planned adoption).
const MAX_REPORTS: usize = 128;

/// The adoption event of a turn's persisted rows, or `None` when the turn
/// produced no application or test result.
///
/// # Errors
/// A row whose content is not decodable TOON (the persistence step already
/// accepted it, so this is a protocol fault).
pub(super) fn turn_adoption_event(rows: &BTreeMap<String, Value>) -> Result<Option<Value>> {
    let mut embeds = Vec::new();
    for (id, row) in rows {
        let content = match row.get("content").and_then(Value::as_str) {
            Some(source) => Plain::new(super::toon::decode(source)?),
            None => Plain::new(Value::Null),
        };
        embeds.push(TurnEmbed::from_row(id, row, &content));
    }
    if !embeds.iter().any(TurnEmbed::starts_adoption) {
        return Ok(None);
    }
    Ok(Some(json!({"embeds": serde_json::to_value(&embeds)?})))
}

/// Report row of a failure before any adoption could be planned.
fn failed(code: &str) -> Value {
    json!({"status": "failed", "code": code})
}

impl Client {
    /// Adopt the candidates of `event` into the chat's focused Project and
    /// record one report per adoption in `state` (send outcome
    /// `projectEmbedAdoptions`). No focus means nothing to do.
    ///
    /// # Errors
    /// Only cancellation; every other failure is a `failed` report row.
    pub(super) async fn adopt_turn_embeds(
        &mut self,
        event: &Value,
        chat: &str,
        state: &mut ProjectCreateState,
    ) -> Result<()> {
        let embeds: Vec<TurnEmbed> = match serde_json::from_value(event["embeds"].clone()) {
            Ok(embeds) => embeds,
            Err(_) => {
                state.push_adoption(failed("invalid_request"));
                return Ok(());
            }
        };
        let rows = match self.adopt_turn_inner(chat, &embeds).await {
            Ok(rows) => rows,
            Err(crate::work::ProjectEmbedAdoptError::Core(Error::Cancelled)) => {
                return Err(Error::Cancelled);
            }
            Err(error) => vec![failed(error.code())],
        };
        for row in rows.into_iter().take(MAX_REPORTS) {
            state.push_adoption(row);
        }
        Ok(())
    }

    async fn adopt_turn_inner(
        &mut self,
        chat: &str,
        embeds: &[TurnEmbed],
    ) -> std::result::Result<Vec<Value>, crate::work::ProjectEmbedAdoptError> {
        let focus = self.projects().active_focus(chat).await?;
        let Some(project) = focus["project_id"].as_str().map(str::to_owned) else {
            return Ok(Vec::new());
        };
        let team = focus["team_id"].as_str().map(str::to_owned);
        let chat_key = self.hosted_file_chat_key(chat).await?;
        let filters = ProjectFilters {
            personal: team.is_none(),
            team_id: team,
            include_archived: None,
        };
        self.projects()
            .with_filters(filters)
            .adopt_turn(&project, chat, &chat_key, embeds)
            .await
    }

    /// The key, decrypted type and decoded content of one existing embed of
    /// `chat`, for the explicit adoption repair. The key comes from the
    /// embed's chat wrapper (or master wrapper in Personal scope), else from
    /// its parent chain; a wrapperless root is derived from the chat key like
    /// `persist_stream_artifacts` derives it. The key never leaves the core.
    ///
    /// # Errors
    /// `Forbidden` for a foreign or mismatched embed, `Crypto` when no key
    /// opens it, and transport errors.
    pub(crate) async fn adoption_embed_source(
        &mut self,
        chat: &str,
        embed: &str,
    ) -> Result<(Key, String, Value)> {
        crate::work::uuid(chat)?;
        crate::work::uuid(embed)?;
        let chat_key = self.hosted_file_chat_key(chat).await?;
        let mut ws = self.socket_with_task_jobs(false).await?;
        let fetched = self.adoption_rows(&mut ws, chat, embed, &chat_key).await;
        let _ = ws.close(None).await;
        self.verify_private_operation()?;
        let (key, row) = fetched?;
        let embed_type = crypto::decrypt_combined(required(&row, "type")?, &key)?;
        let content =
            super::toon::decode(&crypto::decrypt_combined(required(&row, "content")?, &key)?)?;
        Ok((key, embed_type, content))
    }

    async fn adoption_rows(
        &mut self,
        ws: &mut super::transport::Socket,
        chat: &str,
        embed: &str,
        chat_key: &[u8; 32],
    ) -> Result<(Key, Value)> {
        let mut wanted = embed.to_owned();
        let mut first: Option<Value> = None;
        for _ in 0..8 {
            let mut payload = json!({"embed_id": wanted});
            if let Some(team) = self.team()? {
                payload["team_id"] = json!(team);
                payload["chat_id"] = json!(chat);
            }
            send(ws, "request_embed", payload).await?;
            let response = wait(ws, "send_embed_data", "embed_id", &wanted).await?;
            let row = response.get("payload").unwrap_or(&response).clone();
            if row["already_encrypted"] != true || text(&row, "embed_id") != wanted {
                return Err(Error::Forbidden);
            }
            let found = self.wrapper_key(&row, &wanted, chat, chat_key)?;
            let parent = text(&row, "parent_embed_id").to_owned();
            let row_for_embed = first.get_or_insert_with(|| row.clone()).clone();
            if let Some(key) = found {
                return Ok((key, row_for_embed));
            }
            if parent.is_empty() {
                return Ok((crypto::derive_embed_key(chat_key, &wanted)?, row_for_embed));
            }
            wanted = parent;
        }
        Err(Error::Crypto)
    }

    fn wrapper_key(
        &self,
        row: &Value,
        embed: &str,
        chat: &str,
        chat_key: &[u8; 32],
    ) -> Result<Option<Key>> {
        let embed_hash = sha256(embed);
        let chat_hash = sha256(chat);
        for wrapper in row["embed_keys"].as_array().into_iter().flatten() {
            if text(wrapper, "hashed_embed_id") != embed_hash {
                return Err(Error::Forbidden);
            }
            let cipher = required(wrapper, "encrypted_embed_key")?;
            match text(wrapper, "key_type") {
                "chat" if text(wrapper, "hashed_chat_id") == chat_hash => {
                    return Ok(Some(key_from_bytes(&crypto::decrypt_bytes(
                        cipher, chat_key,
                    )?)?));
                }
                "master" if self.team()?.is_none() => {
                    let master = &self.require_session()?.master_key;
                    return Ok(Some(key_from_bytes(&crypto::decrypt_bytes(
                        cipher, master,
                    )?)?));
                }
                _ => {}
            }
        }
        Ok(None)
    }
}
