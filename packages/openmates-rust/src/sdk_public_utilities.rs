//! Pure, credential-free helpers shared with the npm SDK public utilities. Nothing
//! here performs I/O, reads CLI state, environment or local server configuration.
pub use crate::account::{
    INTEREST_TAG_IDS, MemoryField, MemoryType, memory_types,
    normalize_interest_tags as normalize_interest_tag_ids,
};
pub use crate::mentions::MATE_NAMES;
pub use crate::sdk_feedback::{
    ASSISTANT_FEEDBACK_REPORT_TITLE, ASSISTANT_FEEDBACK_THANKS, AssistantFeedbackDecision,
    build_assistant_feedback_decision,
};
use serde_json::{Value, json};

pub const SUPPORT_URL: &str = "https://app.openmates.org/#settings/support";
const SUPPORT_TITLE: &str = "Support OpenMates development";
const SUPPORT_MESSAGE: &str = "Financial support is voluntary and helps keep OpenMates maintained.";
const DEV_BRANCH: &str = "dev";

/// npm `renderSupportInfo`.
pub fn render_support_info() -> String {
    format!("{SUPPORT_TITLE}:\n  {SUPPORT_URL}\n\n{SUPPORT_MESSAGE}")
}

/// npm `defaultCloneBranchForVersion`: prereleases track the dev branch.
pub fn default_clone_branch_for_version(version: &str) -> Option<&'static str> {
    let prerelease = regex::Regex::new(r"-(alpha|beta|rc)(\.|\d|$)").expect("static expression");
    prerelease.is_match(version).then_some(DEV_BRANCH)
}

/// npm `deriveAppUrl` without environment or installed-server overrides: the SDK
/// is configured only by explicit options.
pub fn derive_app_url(api_url: &str) -> String {
    const FALLBACK: &str = "https://app.openmates.org";
    let Ok(mut url) = url::Url::parse(api_url) else {
        return FALLBACK.into();
    };
    let Some(host) = url.host_str().map(str::to_owned) else {
        return FALLBACK.into();
    };
    match host.as_str() {
        "api.dev.openmates.org" => return "https://app.dev.openmates.org".into(),
        "api.openmates.org" => return FALLBACK.into(),
        "localhost" | "127.0.0.1" | "[::1]" => return "http://localhost:5173".into(),
        _ => {}
    }
    if let Some(rest) = host.strip_prefix("api.") {
        let _ = url.set_host(Some(&format!("app.{rest}")));
    }
    url.set_path("");
    url.set_query(None);
    url.set_fragment(None);
    url.to_string().trim_end_matches('/').to_owned()
}

/// npm `getExtForLang`.
pub fn get_ext_for_lang(language: &str) -> String {
    let lower = language.to_lowercase();
    match lower.as_str() {
        "javascript" => "js",
        "typescript" => "ts",
        "python" => "py",
        "ruby" => "rb",
        "rust" => "rs",
        "golang" | "go" => "go",
        "java" => "java",
        "kotlin" => "kt",
        "swift" => "swift",
        "csharp" | "c#" => "cs",
        "cpp" | "c++" => "cpp",
        "c" => "c",
        "html" => "html",
        "css" => "css",
        "scss" => "scss",
        "json" => "json",
        "yaml" | "yml" => "yml",
        "xml" => "xml",
        "sql" => "sql",
        "shell" | "bash" | "zsh" => "sh",
        "powershell" => "ps1",
        "dockerfile" | "docker" => "Dockerfile",
        "markdown" | "md" => "md",
        "toml" => "toml",
        "ini" => "ini",
        "lua" => "lua",
        "r" => "r",
        "php" => "php",
        "perl" => "pl",
        "scala" => "scala",
        "svelte" => "svelte",
        "vue" => "vue",
        "jsx" => "jsx",
        "tsx" => "tsx",
        "" => "txt",
        other => return other.to_owned(),
    }
    .to_owned()
}

const AI_LIKELY: f64 = 0.7;
const AI_POSSIBLE: f64 = 0.4;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ImagesAiDetectionClassification {
    LikelyAiGenerated,
    PossiblyAiGenerated,
    LikelyNotAiGenerated,
    Unavailable,
}
impl ImagesAiDetectionClassification {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::LikelyAiGenerated => "likely_ai_generated",
            Self::PossiblyAiGenerated => "possibly_ai_generated",
            Self::LikelyNotAiGenerated => "likely_not_ai_generated",
            Self::Unavailable => "unavailable",
        }
    }
}
/// npm `classifyImagesAiDetection`.
pub fn classify_images_ai_detection(score: Option<f64>) -> ImagesAiDetectionClassification {
    match score {
        Some(s) if s.is_finite() && s > AI_LIKELY => {
            ImagesAiDetectionClassification::LikelyAiGenerated
        }
        Some(s) if s.is_finite() && s > AI_POSSIBLE => {
            ImagesAiDetectionClassification::PossiblyAiGenerated
        }
        Some(s) if s.is_finite() => ImagesAiDetectionClassification::LikelyNotAiGenerated,
        _ => ImagesAiDetectionClassification::Unavailable,
    }
}
/// npm `formatImagesAiDetectionLabel`.
pub fn format_images_ai_detection_label(
    classification: ImagesAiDetectionClassification,
) -> &'static str {
    match classification {
        ImagesAiDetectionClassification::LikelyAiGenerated => "Likely AI-generated",
        ImagesAiDetectionClassification::PossiblyAiGenerated => "Possibly AI-generated",
        ImagesAiDetectionClassification::LikelyNotAiGenerated => "Likely not AI-generated",
        ImagesAiDetectionClassification::Unavailable => "Detection unavailable",
    }
}
/// npm `buildImagesAiDetectionSummary` over an upload-response JSON object.
pub fn build_images_ai_detection_summary(upload: &Value, file_path: &str) -> Value {
    let detection = upload.get("ai_detection").filter(|d| !d.is_null());
    let status = detection
        .and_then(|d| d["status"].as_str())
        .unwrap_or(if detection.is_some() {
            "success"
        } else {
            "unavailable"
        });
    let score = (status == "success")
        .then(|| detection.and_then(|d| d["ai_generated"].as_f64()))
        .flatten();
    let classification = classify_images_ai_detection(score);
    let basename = file_path.rsplit(['/', '\\']).next().unwrap_or(file_path);
    json!({
        "file": file_path,
        "filename": upload["filename"].as_str().filter(|s| !s.is_empty()).unwrap_or(basename),
        "content_type": upload["content_type"],
        "embed_id": upload["embed_id"],
        "deduplicated": upload["deduplicated"],
        "stored": true,
        "status": status,
        "provider": detection.map(|d| d["provider"].clone()).filter(|p| !p.is_null()).unwrap_or(Value::Null),
        "ai_generated": score,
        "classification": classification.as_str(),
        "label": format_images_ai_detection_label(classification),
        "error": detection.map(|d| d["error"].clone()).filter(|e| !e.is_null()).unwrap_or(Value::Null),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn support_branch_and_extension_helpers_match_npm() {
        assert_eq!(
            render_support_info(),
            "Support OpenMates development:\n  https://app.openmates.org/#settings/support\n\nFinancial support is voluntary and helps keep OpenMates maintained."
        );
        for (version, branch) in [
            ("1.2.0", None),
            ("1.2.0-alpha.1", Some("dev")),
            ("1.2.0-rc1", Some("dev")),
            ("1.2.0-beta", Some("dev")),
            ("1.2.0-rcx", None),
        ] {
            assert_eq!(
                default_clone_branch_for_version(version),
                branch,
                "{version}"
            );
        }
        for (language, ext) in [
            ("TypeScript", "ts"),
            ("C#", "cs"),
            ("docker", "Dockerfile"),
            ("", "txt"),
            ("Haskell", "haskell"),
            ("YML", "yml"),
        ] {
            assert_eq!(get_ext_for_lang(language), ext);
        }
    }
    #[test]
    fn app_url_derivation_matches_npm_host_rules() {
        for (api, app) in [
            ("https://api.openmates.org", "https://app.openmates.org"),
            (
                "https://api.dev.openmates.org/",
                "https://app.dev.openmates.org",
            ),
            ("http://127.0.0.1:8000", "http://localhost:5173"),
            (
                "https://api.example.test:8443/v1?x=1",
                "https://app.example.test:8443",
            ),
            ("https://selfhost.example", "https://selfhost.example"),
            ("not a url", "https://app.openmates.org"),
        ] {
            assert_eq!(derive_app_url(api), app, "{api}");
        }
    }
    #[test]
    fn registries_and_ai_detection_match_npm() {
        assert_eq!(
            normalize_interest_tag_ids(&["finance", "personal_finances", "marketing"]).unwrap(),
            ["finance_bookkeeping", "personal_finances", "marketing"]
        );
        assert!(normalize_interest_tag_ids(&["nope"]).is_err());
        assert_eq!(MATE_NAMES[0], ("software_development", "Sophia"));
        assert_eq!(
            classify_images_ai_detection(Some(0.71)),
            ImagesAiDetectionClassification::LikelyAiGenerated
        );
        assert_eq!(
            classify_images_ai_detection(Some(0.7)),
            ImagesAiDetectionClassification::PossiblyAiGenerated
        );
        assert_eq!(
            classify_images_ai_detection(Some(0.4)),
            ImagesAiDetectionClassification::LikelyNotAiGenerated
        );
        assert_eq!(
            classify_images_ai_detection(Some(f64::NAN)),
            ImagesAiDetectionClassification::Unavailable
        );
        let summary = build_images_ai_detection_summary(
            &json!({"content_type":"image/png","embed_id":"e","deduplicated":false,"ai_detection":{"status":"success","ai_generated":0.9,"provider":"p"}}),
            "/tmp/a/pic.png",
        );
        assert_eq!(
            (
                summary["filename"].clone(),
                summary["label"].clone(),
                summary["ai_generated"].clone()
            ),
            (json!("pic.png"), json!("Likely AI-generated"), json!(0.9))
        );
        let none = build_images_ai_detection_summary(&json!({"filename":"x.png"}), "x.png");
        assert_eq!(
            (
                none["status"].clone(),
                none["classification"].clone(),
                none["ai_generated"].clone()
            ),
            (json!("unavailable"), json!("unavailable"), Value::Null)
        );
    }
}
