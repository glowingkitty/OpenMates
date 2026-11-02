//! Send-time @mention resolution against the server Apps catalog.
//!
//! Mirrors `openmates-cli/src/client.ts::buildMentionContext` plus the
//! `parseMentions` call in `cli.ts::sendMessageStreaming`: static chat models
//! and mates, `/v1/apps?include_unavailable=true` for skills, focus modes and
//! memory categories. Memory-entry mentions need decrypted memories, which this
//! client does not list yet; they are reported as unresolved, never guessed.
//! Update: decrypted Personal memories (`Account::memories`) are now loaded
//! when a token is still unresolved; entries are the last resolution step, so
//! earlier matches are identical to TS.
use super::*;
use crate::mentions::{self, MentionContext, MentionParseResult};

impl Client {
    /// Resolve display mentions (`@Gemini-3.8-Flash`, `@Sophia`,
    /// `@Web-Search`, ...) to wire syntax. Unknown mentions keep their text
    /// and are returned in `unresolved` for the caller to refuse or report.
    pub async fn resolve_mentions(&mut self, message: &str) -> Result<MentionParseResult> {
        let mut result = MentionParseResult {
            processed_message: message.to_owned(),
            ..Default::default()
        };
        if mentions::extract_mention_tokens(message).is_empty() {
            return Ok(result);
        }
        let apps = match self
            .request(Method::GET, "/v1/apps?include_unavailable=true", None)
            .await
        {
            Ok(data) => mentions::apps_from_json(&data),
            Err(Error::Cancelled) => return Err(Error::Cancelled),
            // Same as the TypeScript CLI: without the catalog, app mentions are
            // reported as unresolved by the parser below instead of failing.
            Err(_) => vec![],
        };
        let apps_for_memories = apps.clone();
        result = mentions::parse_mentions(
            message,
            &MentionContext::with_apps(apps),
            &mentions::today_utc(),
        );
        if !result.unresolved.is_empty() && self.session().is_some() {
            match self.account().memories().await {
                Ok(rows) => {
                    let mut context = MentionContext::with_apps(apps_for_memories);
                    context.memory_entries = mentions::memory_entries_from_json(&rows);
                    result = mentions::parse_mentions(message, &context, &mentions::today_utc());
                }
                Err(Error::Cancelled) => return Err(Error::Cancelled),
                // TS buildMentionContext: memories unavailable (Team scope,
                // offline) leave the unresolved mentions reported as such.
                Err(_) => {}
            }
        }
        // `@openmates` addresses the Team AI and stays literal in Team scope.
        if self.team().ok().flatten().is_some() {
            result
                .unresolved
                .retain(|mention| !mention.original.eq_ignore_ascii_case("@openmates"));
        }
        Ok(result)
    }
}
