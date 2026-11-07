//! URL classification of pasted links for the web composer: YouTube video URL,
//! GitHub repository URL and the 11-character YouTube video id. Ports
//! `isYouTubeUrl`, `isGitHubRepoUrl` and `extractYouTubeVideoId`
//! (`enter_message/services/urlMetadataService.ts`) onto the shared `composer`
//! unit. Pure: the page keeps the metadata fetches and embed creation.
//! spec: specifications/features/message-input#message-input.suggestions.contextual
use super::protocol;
use super::utf16::WS_CLASS;
use regex::Regex;
use serde_json::{Value, json};
use std::sync::OnceLock;
use url::Url;

/// Owners that are GitHub site sections, not accounts.
const RESERVED_OWNERS: [&str; 6] = ["features", "topics", "collections", "marketplace", "explore", "login"];

struct Patterns {
    youtube: Regex,
    github: Regex,
    video_ids: [Regex; 5],
}

fn patterns() -> &'static Patterns {
    static PATTERNS: OnceLock<Patterns> = OnceLock::new();
    PATTERNS.get_or_init(|| {
        let build = |p: &str| Regex::new(p).expect("fixed url pattern compiles");
        // JS `/i` folds ASCII only, so the scheme and host literals are ASCII-folded (`(?i-u:...)`);
        // `\s` in the owner/repo segments is the JS whitespace set, `.` excludes the JS line terminators.
        Patterns {
            youtube: build(r"^(?i-u:https?://(www\.|m\.)?(youtube\.com/(watch\?v=|embed/|shorts/|v/)|youtu\.be/))"),
            github: build(&format!(
                r"^(?i-u:https?://(www\.)?github\.com/)[^/{WS_CLASS}]+/[^/?#{WS_CLASS}]+/?(?:[?#][^\n\r\x{{2028}}\x{{2029}}]*)?$"
            )),
            video_ids: [
                build(r"[?&]v=([a-zA-Z0-9_-]{11})"),
                build(r"youtu\.be/([a-zA-Z0-9_-]{11})"),
                build(r"youtube\.com/embed/([a-zA-Z0-9_-]{11})"),
                build(r"youtube\.com/shorts/([a-zA-Z0-9_-]{11})"),
                build(r"youtube\.com/v/([a-zA-Z0-9_-]{11})"),
            ],
        }
    })
}

/// `isYouTubeUrl`.
fn is_youtube_url(url: &str) -> bool {
    patterns().youtube.is_match(url)
}

/// `isGitHubRepoUrl`: the shape check, then exactly `/owner/repo` after WHATWG path
/// normalisation and an owner that is not a reserved site section.
fn is_github_repo_url(url: &str) -> bool {
    if !patterns().github.is_match(url) {
        return false;
    }
    let Ok(parsed) = Url::parse(url) else { return false };
    let path = parsed.path();
    let path = path.strip_suffix('/').unwrap_or(path);
    let parts: Vec<&str> = path.split('/').filter(|s| !s.is_empty()).collect();
    matches!(parts.as_slice(), [owner, _] if !RESERVED_OWNERS.contains(owner))
}

/// `extractYouTubeVideoId`: first pattern (in TypeScript order) that matches wins.
fn youtube_video_id(url: &str) -> Option<String> {
    patterns().video_ids.iter().find_map(|re| re.captures(url).map(|c| c[1].to_string()))
}

/// `{url}` -> `{youtube, githubRepo, videoId}` (`videoId` is the 11-character id or `null`).
///
/// # Errors
/// `protocol` when the payload is not `{url: string}`.
pub fn url_classify_json(input: &str) -> Result<String, String> {
    let payload: Value = serde_json::from_str(input).map_err(protocol)?;
    let url = payload.get("url").and_then(Value::as_str).ok_or("protocol")?;
    Ok(json!({"youtube": is_youtube_url(url), "githubRepo": is_github_repo_url(url), "videoId": youtube_video_id(url)}).to_string())
}
