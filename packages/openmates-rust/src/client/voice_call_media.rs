//! Which generated media the voice-call stage shows, shared by the native shells.
//! Pure policy over already-decrypted embed content: walk candidate embeds,
//! expand generated-media groups, keep finished image/video files, then pick
//! the displayed item. Mirrors web `voiceCallMedia.ts` (`resolve`),
//! `generatedMediaGroup.ts` and `voiceCall.ts` (`refreshCallMedia`), pinned by
//! `tests/fixtures/ts_voice_call_media.json`. Fetching and decrypting the bytes
//! stays with the shell's S3 media client. Spec: `client-core`.
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{HashMap, HashSet, VecDeque};

/// Web visits at most this many embed ids per resolve.
const MAX_VISITED: usize = 64;

/// One embed as the shell holds it: row fields plus decrypted content.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct VoiceCallMediaEmbed {
    /// Embed id.
    pub embed_id: String,
    /// Row-level app id (fallback when content has none).
    pub app_id: Option<String>,
    /// Row-level skill id (fallback).
    pub skill_id: Option<String>,
    /// Row-level embed type (fallback).
    pub embed_type: Option<String>,
    /// Row-level status (fallback).
    pub status: Option<String>,
    /// Decryption failed: the embed is skipped.
    pub decryption_failed: bool,
    /// Decryption still pending: the embed is skipped.
    pub decryption_pending: bool,
    /// Decrypted content object (anything else is treated as no content).
    pub content: Value,
}

/// Media kind shown on the stage.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum VoiceCallMediaKind {
    /// Still image.
    Image,
    /// Video clip.
    Video,
}

/// Which stored file variant to fetch.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum VoiceCallMediaVariant {
    /// `files.original`.
    Original,
    /// `files.preview` (images only).
    Preview,
}

/// A displayable media item. Carries no key material; the shell reads
/// `aes_key`/nonce from the embed content it already holds.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct VoiceCallStageMedia {
    /// Embed that owns the file.
    pub embed_id: String,
    /// Image or video.
    pub kind: VoiceCallMediaKind,
    /// File variant chosen.
    pub variant: VoiceCallMediaVariant,
    /// Object key of the encrypted file.
    pub s3_key: String,
    /// Base URL of the object store.
    pub s3_base_url: String,
    /// Declared mime type of the file, if any.
    pub mime_type: Option<String>,
}

/// Displayed item choice after a resolve.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct VoiceCallStageSelection {
    /// Index into the items to display; `None` leaves the stage unchanged.
    pub displayed_index: Option<u32>,
    /// True when an item not yet presented was chosen (stage expands).
    pub fresh: bool,
    /// Ids to add to the presented set (every item, in order).
    pub newly_presented: Vec<String>,
}

/// Generation skills whose invocation may own several output embeds
/// (`isGeneratedMediaSkill`).
fn is_generated_media_skill(app: Option<&str>, skill: Option<&str>) -> bool {
    let (Some(app), Some(skill)) = (app, skill) else {
        return false;
    };
    matches!(
        (app, skill),
        (
            "images",
            "generate" | "generate_draft" | "vectorize" | "modify"
        ) | ("audio", "generate" | "speak")
            | ("music" | "videos" | "models3d", "generate")
            | ("design", "embroidery")
    )
}

/// Non-empty string child ids of `content.embed_ids` (`generatedMediaChildIds`).
fn child_ids(content: &Value) -> Vec<String> {
    content
        .get("embed_ids")
        .and_then(Value::as_array)
        .map(|ids| {
            ids.iter()
                .filter_map(Value::as_str)
                .filter(|id| !id.is_empty())
                .map(str::to_owned)
                .collect()
        })
        .unwrap_or_default()
}

/// First present non-null string-or-other value, content before row field,
/// as JS `content.x ?? embed.x`.
fn pick<'a>(content: &'a Value, key: &str, row: Option<&'a str>) -> Option<&'a str> {
    match content.get(key) {
        Some(Value::Null) | None => row,
        Some(v) => v.as_str(),
    }
}

fn stage_media(embed: &VoiceCallMediaEmbed) -> Result<Option<VoiceCallStageMedia>, Vec<String>> {
    let content = &embed.content;
    let app = pick(content, "app_id", embed.app_id.as_deref());
    let skill = pick(content, "skill_id", embed.skill_id.as_deref());
    let kind_type = pick(content, "type", embed.embed_type.as_deref());
    let children = child_ids(content);
    let generated = is_generated_media_skill(app, skill);
    if !children.is_empty() && generated {
        return Err(children);
    }
    let kind = if kind_type == Some("generated_image") || (app == Some("images") && generated) {
        VoiceCallMediaKind::Image
    } else if kind_type == Some("generated_video")
        || (app == Some("videos") && skill == Some("generate"))
    {
        VoiceCallMediaKind::Video
    } else {
        return Ok(None);
    };
    if pick(content, "status", embed.status.as_deref()) != Some("finished") {
        return Ok(None);
    }
    let files = content.get("files");
    let original = files
        .and_then(|f| f.get("original"))
        .filter(|v| v.is_object());
    let (file, variant) = match (original, kind) {
        (Some(file), _) => (file, VoiceCallMediaVariant::Original),
        (None, VoiceCallMediaKind::Image) => {
            match files
                .and_then(|f| f.get("preview"))
                .filter(|v| v.is_object())
            {
                Some(file) => (file, VoiceCallMediaVariant::Preview),
                None => return Ok(None),
            }
        }
        (None, VoiceCallMediaKind::Video) => return Ok(None),
    };
    // Web also calls hasMediaEncryptionMetadata(file, nonce), but nonce is
    // always a string there, so that check can never reject; only the three
    // string fields gate a file.
    let (Some(key), Some(base), Some(_aes)) = (
        file.get("s3_key").and_then(Value::as_str),
        content.get("s3_base_url").and_then(Value::as_str),
        content.get("aes_key").and_then(Value::as_str),
    ) else {
        return Ok(None);
    };
    Ok(Some(VoiceCallStageMedia {
        embed_id: embed.embed_id.clone(),
        kind,
        variant,
        s3_key: key.to_owned(),
        s3_base_url: base.to_owned(),
        mime_type: file
            .get("mime_type")
            .and_then(Value::as_str)
            .map(str::to_owned),
    }))
}

/// Resolves the stage media list for candidate embed ids (call media ids,
/// newest first), visiting at most 64 ids and expanding generated-media group
/// children after the remaining candidates, like the web resolver.
pub fn voice_call_stage_media(
    candidate_ids_newest_first: &[String],
    embeds: &HashMap<String, VoiceCallMediaEmbed>,
) -> Vec<VoiceCallStageMedia> {
    let mut queue: VecDeque<String> = candidate_ids_newest_first.iter().cloned().collect();
    let mut seen: HashSet<String> = HashSet::new();
    let mut media = Vec::new();
    while seen.len() < MAX_VISITED {
        let Some(id) = queue.pop_front() else { break };
        if !seen.insert(id.clone()) {
            continue;
        }
        let Some(embed) = embeds.get(&id) else {
            continue;
        };
        if embed.decryption_failed || embed.decryption_pending || !embed.content.is_object() {
            continue;
        }
        match stage_media(embed) {
            Err(children) => queue.extend(children),
            Ok(Some(item)) => media.push(item),
            Ok(None) => {}
        }
    }
    media
}

/// Chooses the displayed item: the first not yet presented one (fresh), else
/// the currently displayed embed's index (0 when it is gone), else nothing
/// when there are no items (`refreshCallMedia`).
pub fn voice_call_stage_selection(
    items: &[VoiceCallStageMedia],
    presented: &[String],
    displayed_embed_id: Option<&str>,
) -> VoiceCallStageSelection {
    let newly_presented = items.iter().map(|item| item.embed_id.clone()).collect();
    let fresh = items
        .iter()
        .position(|item| !presented.contains(&item.embed_id));
    let (displayed_index, is_fresh) = match fresh {
        Some(index) => (Some(index as u32), true),
        None if items.is_empty() => (None, false),
        None => (
            Some(
                displayed_embed_id
                    .and_then(|id| items.iter().position(|item| item.embed_id == id))
                    .unwrap_or(0) as u32,
            ),
            false,
        ),
    };
    VoiceCallStageSelection {
        displayed_index,
        fresh: is_fresh,
        newly_presented,
    }
}

#[cfg(test)]
#[path = "voice_call_media_tests.rs"]
mod tests;
